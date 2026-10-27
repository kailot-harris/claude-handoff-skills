#!/usr/bin/env python3
"""Run log, batch bookkeeping and approved-template registry. Spec §7, §8.

Single runs (--run-id can be replaced by --label on record-result,
save-output, set-status and show, once new-run registered that label):
  runlog.py init
  runlog.py new-run --brief FILE [--model M] [--label TEXT] [--batch-id B --item-id I] [--worktree PATH]
  runlog.py record-result (--run-id ID | --label TEXT) --result FILE
  runlog.py save-output (--run-id ID | --label TEXT) --name NAME --file FILE
  runlog.py set-status (--run-id ID | --label TEXT) --status STATUS [--reason TEXT]
  runlog.py show (--run-id ID | --label TEXT)
  runlog.py labels                                           list every label and the run ids under it
Batches:
  runlog.py batch-new --template FILE --items ITEMS.json
  runlog.py batch-expand --batch-id B --item-id I            write the expanded brief for one item
  runlog.py batch-status --batch-id B                        counts, early-stop decision, free slots
  runlog.py batch-approve-pilot --batch-id B --confirmed-by-user
  runlog.py batch-sample --batch-id B [--rate 0.2] [--seed N]
  runlog.py batch-report --batch-id B

Every command prints JSON. Exit 0 = ok, 1 = blocked/invalid, 2 = usage error.

Labels (spec §12.1): usage data showed every project hand-naming files
alongside the run log (`brief_issue11.md`, `result_p9a.json`, ...) because
the generated run_id is opaque. `--label` on new-run gives that same
human-readable handle a first-class home in meta.json and an index
(`labels.json`) instead of a parallel set of hand-named files. A batch
item's `item_id` is automatically usable as a label too.

Batch pilot threshold (spec §12.1): a batch with fewer than
BATCH_PILOT_MIN_ITEMS items skips the mandatory pilot approval — usage data
showed a 4-item batch's pilot being abandoned in favor of dispatching every
item by hand through plain new-run. For a batch that small, all items run
immediately anyway and the early-stop rule (over a window that is now the
whole batch) halts on the very first failure, which is roughly the same
protection a 2-item pilot would have given. This size-based skip does not
register the template hash as approved — only an explicit
batch-approve-pilot does that — so a later, larger batch using the same
template still gets a real pilot.
"""
import json
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import emit, now_iso, parse_cli, read_json, read_text, runs_dir, sha256_text, write_json, write_text  # noqa: E402
from scan_secrets import find_secrets, public_findings, redact_text  # noqa: E402
from validate_brief import expand_item, validate_text  # noqa: E402
from validate_result import validate as validate_result_obj  # noqa: E402

CONCURRENCY_CAP = 4           # spec §8.1, fixed
EARLY_STOP_WINDOW = 10        # first N items ...
EARLY_STOP_RATE = 0.20        # ... halt if more than this fraction fail
BATCH_PILOT_MIN_ITEMS = 5     # spec §12.1: batches smaller than this skip the pilot gate
EXCERPT_LIMIT = 2048
TERMINAL_OK = {"success"}
ORCH_STATUSES = {"verified", "evidence_mismatch", "merged", "merge_conflict", "rejected", "kept"}


def run_dir(root, run_id):
    return runs_dir(root) / run_id


def labels_path(root):
    return runs_dir(root) / "labels.json"


def load_labels(root):
    return read_json(labels_path(root), default={})


def register_label(root, label, run_id):
    if not label:
        return
    labels = load_labels(root)
    labels.setdefault(label, [])
    if run_id not in labels[label]:
        labels[label].append(run_id)
    runs_dir(root).mkdir(parents=True, exist_ok=True)
    write_json(labels_path(root), labels)


def resolve_run_id(root, opt, required=True):
    """--run-id wins if given; otherwise --label resolves to its most
    recently registered run. Covers record-result/save-output/set-status/show
    so a session can track a run by the same human-readable handle it used
    at dispatch, instead of copying the generated run_id around by hand."""
    rid = opt.get("run_id")
    if rid:
        return rid
    label = opt.get("label")
    if label:
        ids = load_labels(root).get(label)
        if not ids:
            emit({"ok": False, "error": f"No run is registered under label `{label}`."}, 2)
        return ids[-1]
    if required:
        emit({"ok": False, "error": "--run-id or --label is required."}, 2)
    return None


def batch_dir(root, batch_id):
    return runs_dir(root) / "batches" / batch_id


def approved_path(root):
    return runs_dir(root) / "batches" / ".approved-templates"


def need(opt, *keys):
    for k in keys:
        if opt.get(k.replace("-", "_")) is None:
            emit({"ok": False, "error": f"--{k} is required."}, 2)


def load_meta(root, run_id):
    m = read_json(run_dir(root, run_id) / "meta.json")
    if m is None:
        emit({"ok": False, "error": f"Unknown run `{run_id}`."}, 2)
    return m


def save_meta(root, m):
    write_json(run_dir(root, m["run_id"]) / "meta.json", m)


def new_id(seed_text):
    import time
    ts = __import__("datetime").datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    salt = f"{seed_text}{time.time()}{random.random()}"
    return f"{ts}-{sha256_text(salt)[:6]}"


def ensure_gitignore(root):
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        base = Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else Path.cwd()
    except FileNotFoundError:
        base = Path.cwd()
    rd = runs_dir(root).resolve()
    try:
        rel = rd.relative_to(base.resolve())
        entry = f"/{str(rel).rstrip('/')}/"
    except ValueError:
        entry = str(runs_dir(root))
    gi = base / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    variants = {entry, entry.lstrip("/"), entry.rstrip("/"), entry.strip("/")}
    if any(line.strip() in variants for line in lines):
        return False
    write_text(gi, "\n".join(lines + ["# subagent-brief run logs (may contain sensitive output)", entry]) + "\n")
    return True


def cmd_init(opt):
    (runs_dir(opt.get("runs_dir")) / "batches").mkdir(parents=True, exist_ok=True)
    added = ensure_gitignore(opt.get("runs_dir"))
    emit({"ok": True, "runs_dir": str(runs_dir(opt.get("runs_dir"))), "gitignore_updated": added})


def cmd_new_run(opt):
    need(opt, "brief")
    root = opt.get("runs_dir")
    runs_dir(root).mkdir(parents=True, exist_ok=True)
    ensure_gitignore(root)
    text = read_text(opt["brief"])
    v = validate_text(text)
    secrets = find_secrets(text, root)
    if v["errors"] or secrets:
        emit({"ok": False, "error": "Brief failed validation; not dispatched.", "errors": v["errors"],
              "secrets": public_findings(secrets)}, 1)

    template_hash = None
    pilot = False
    batch_id = opt.get("batch_id")
    item_id = opt.get("item_id")
    if batch_id is not None:
        b = load_batch(root, batch_id)
        need(opt, "item-id")
        if b.get("halted"):
            emit({"ok": False, "error": "Batch halted by early stop; no further dispatch."}, 1)
        pilot = item_id in (b.get("pilot_items") or [])
        if not b.get("pilot_approved") and not pilot:
            emit({"ok": False, "error": "Pilot not yet approved; only pilot items may be dispatched."}, 1)
        template_hash = b["template_hash"]

    run_id = new_id(text)
    filled = text.replace("{{run_id}}", run_id).replace("{{item_id}}", item_id if item_id is not None else "null")
    d = run_dir(root, run_id)
    (d / "outputs").mkdir(parents=True, exist_ok=True)
    write_text(d / "brief.md", filled)
    # --label gives the run a human-readable handle (spec §12.1); a batch
    # item's own item_id is usable as one automatically even without --label.
    label = opt.get("label")
    meta = {
        "run_id": run_id, "created_at": now_iso(), "model": opt.get("model"), "label": label,
        "template": v["template"], "schema_version": v["schema_version"],
        "template_hash": template_hash or sha256_text(text), "brief_hash": sha256_text(filled),
        "criteria_count": v["criteria_count"], "tiers": v["tiers"],
        "batch_id": batch_id, "item_id": item_id, "pilot": pilot, "worktree": opt.get("worktree"),
        "status": "dispatched", "failure_reason": None, "redactions": [], "history": [],
    }
    save_meta(root, meta)
    for lbl in {x for x in (label, item_id) if x}:
        register_label(root, lbl, run_id)
    emit({"ok": True, "run_id": run_id, "brief_path": str(d / "brief.md"), "label": label, "warnings": v["warnings"]})


def truncate_excerpts(obj, d):
    for ev in obj.get("evidence", []):
        ex = ev.get("excerpt")
        if isinstance(ex, str) and len(ex) > EXCERPT_LIMIT:
            fname = Path("outputs") / f"evidence-{re.sub(r'[^A-Za-z0-9_-]', '_', ev['id'])}.txt"
            write_text(d / fname, ex)
            marker = "\n...[truncated; see full_output_path]"
            ev["excerpt"] = ex[:EXCERPT_LIMIT - len(marker)] + marker
            ev["full_output_path"] = str(fname)
    return obj


def cmd_record_result(opt):
    need(opt, "result")
    root = opt.get("runs_dir")
    m = load_meta(root, resolve_run_id(root, opt))
    d = run_dir(root, m["run_id"])
    red_text, findings = redact_text(read_text(opt["result"]), root)
    # Truncate long evidence excerpts BEFORE schema validation, not after —
    # otherwise a long-but-otherwise-valid excerpt fails maxLength before it
    # ever gets the chance to be truncated.
    from validate_result import extract_json
    pre_obj = extract_json(red_text)
    if isinstance(pre_obj, dict):
        pre_obj = truncate_excerpts(pre_obj, d)
        rep = validate_result_obj(json.dumps(pre_obj), m["run_id"], m["criteria_count"])
    else:
        rep = validate_result_obj(red_text, m["run_id"], m["criteria_count"])
    if rep["valid"]:
        obj = rep["result"]
        write_json(d / "result.json", obj)
        m["status"] = rep["status"]
        m["failure_reason"] = None
        m["files_changed"] = (obj.get("changes") or {}).get("files_changed") or []
    else:
        write_text(d / "raw_output.txt", red_text)
        m["status"] = "failed"
        m["failure_reason"] = "schema_violation"
        m["files_changed"] = None
    m["completed_at"] = now_iso()
    if findings:
        m.setdefault("redactions", []).append({
            "file": "result.json" if rep["valid"] else "raw_output.txt",
            "count": len(findings), "types": sorted({f["type"] for f in findings}),
        })
    save_meta(root, m)
    emit({"ok": rep["valid"], "run_id": m["run_id"], "status": m["status"], "failure_reason": m["failure_reason"],
          "errors": rep["errors"], "redactions": len(findings)}, 0 if rep["valid"] else 1)


def cmd_save_output(opt):
    need(opt, "name", "file")
    root = opt.get("runs_dir")
    m = load_meta(root, resolve_run_id(root, opt))
    red_text, findings = redact_text(read_text(opt["file"]), root)
    rel = Path("outputs") / Path(opt["name"]).name
    write_text(run_dir(root, m["run_id"]) / rel, red_text)
    if findings:
        m.setdefault("redactions", []).append({"file": str(rel), "count": len(findings),
                                               "types": sorted({f["type"] for f in findings})})
        save_meta(root, m)
    emit({"ok": True, "path": str(rel), "redactions": len(findings)})


def cmd_set_status(opt):
    need(opt, "status")
    if opt["status"] not in ORCH_STATUSES:
        emit({"ok": False, "error": f"--status must be one of: {', '.join(sorted(ORCH_STATUSES))}"}, 2)
    root = opt.get("runs_dir")
    m = load_meta(root, resolve_run_id(root, opt))
    m.setdefault("history", []).append({"at": now_iso(), "status": opt["status"], "reason": opt.get("reason")})
    m["review"] = opt["status"]
    if opt["status"] == "evidence_mismatch":
        m["status"] = "failed"
        m["failure_reason"] = "evidence_mismatch"
    if opt["status"] == "merge_conflict":
        m["failure_reason"] = "merge_conflict"
    save_meta(root, m)
    emit({"ok": True, "run_id": m["run_id"], "status": m["status"], "review": m["review"]})


def cmd_show(opt):
    root = opt.get("runs_dir")
    run_id = resolve_run_id(root, opt)
    emit({"ok": True, "meta": load_meta(root, run_id),
          "result": read_json(run_dir(root, run_id) / "result.json")})


def cmd_labels(opt):
    root = opt.get("runs_dir")
    emit({"ok": True, "labels": load_labels(root)})


# ---- batches ----------------------------------------------------------

def approved_hashes(root):
    a = read_json(approved_path(root), default={"entries": []})
    return {e["template_hash"] for e in a["entries"]}


def load_batch(root, batch_id):
    b = read_json(batch_dir(root, batch_id) / "batch.json")
    if b is None:
        emit({"ok": False, "error": f"Unknown batch `{batch_id}`."}, 2)
    return b


def save_batch(root, b):
    write_json(batch_dir(root, b["batch_id"]) / "batch.json", b)


def batch_runs(root, batch_id):
    metas = []
    base = runs_dir(root)
    if base.exists():
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            m = read_json(d / "meta.json")
            if m and m.get("batch_id") == batch_id:
                metas.append(m)
    metas.sort(key=lambda m: (m.get("created_at", ""), m.get("run_id", "")))
    return metas


def cmd_batch_new(opt):
    need(opt, "template", "items")
    root = opt.get("runs_dir")
    text = read_text(opt["template"])
    v = validate_text(text)
    if v["template"] != "batch":
        emit({"ok": False, "error": "Template must set `template: batch`."}, 1)
    items = json.loads(read_text(opt["items"]))
    ids = [str(i.get("id")) if i.get("id") is not None else None for i in items]
    if None in ids or len(set(ids)) != len(ids):
        emit({"ok": False, "error": "Every item needs a unique `id`."}, 1)
    bad = {}
    for it in items:
        exp = expand_item(text, it)
        errs = validate_text(exp, expect_template="batch")["errors"]
        if find_secrets(exp, root):
            errs = errs + ["possible secret(s) in expanded brief"]
        if errs:
            bad[str(it["id"])] = errs
    if bad or v["errors"] or find_secrets(text, root):
        emit({"ok": False, "error": "Batch failed validation; not created.", "errors": v["errors"],
              "item_errors": bad}, 1)

    template_hash = sha256_text(text)
    batch_id = f"b-{new_id(text)}"
    d = batch_dir(root, batch_id)
    d.mkdir(parents=True, exist_ok=True)
    ensure_gitignore(root)
    write_text(d / "template.md", text)
    write_json(d / "items.json", items)
    # spec §12.1: a batch this small skips the mandatory pilot. All of its
    # items dispatch immediately once created, and the early-stop rule
    # (window = the whole batch, below this size) halts on the first failure
    # anyway, which is roughly the protection a 2-item pilot would have
    # given. This does NOT register the template hash as approved — only an
    # explicit batch-approve-pilot does that — so a later, larger batch on
    # the same template still gets a real pilot.
    pilot_skip_reason = None
    if len(items) < BATCH_PILOT_MIN_ITEMS:
        pilot_required = False
        pilot_skip_reason = f"batch has {len(items)} item(s), fewer than {BATCH_PILOT_MIN_ITEMS}"
    else:
        pilot_required = template_hash not in approved_hashes(root)
        if not pilot_required:
            pilot_skip_reason = "template already approved by a previous pilot"
    n_pilot = min(2, len(items)) if pilot_required else 0
    pilot_items = ids[:n_pilot]
    b = {"batch_id": batch_id, "created_at": now_iso(), "template_hash": template_hash, "item_count": len(items),
         "pilot_required": pilot_required, "pilot_items": pilot_items, "pilot_approved": not pilot_required,
         "pilot_skip_reason": pilot_skip_reason, "sampled": [], "sample_rate": None, "halted": False}
    save_batch(root, b)
    emit({"ok": True, "batch_id": batch_id, "template_hash": template_hash, "item_count": len(items),
          "pilot_required": pilot_required, "pilot_items": pilot_items, "pilot_skip_reason": pilot_skip_reason,
          "concurrency_cap": CONCURRENCY_CAP, "warnings": v["warnings"]})


def cmd_batch_expand(opt):
    need(opt, "batch-id", "item-id")
    root = opt.get("runs_dir")
    b = load_batch(root, opt["batch_id"])
    d = batch_dir(root, b["batch_id"])
    items = read_json(d / "items.json")
    matches = [i for i in items if str(i.get("id")) == opt["item_id"]]
    if not matches:
        emit({"ok": False, "error": f"No item `{opt['item_id']}` in batch."}, 2)
    if not b.get("pilot_approved") and opt["item_id"] not in (b.get("pilot_items") or []):
        emit({"ok": False, "error": "Pilot not yet approved; only pilot items may be dispatched.",
              "pilot_items": b.get("pilot_items") or []}, 1)
    if b.get("halted"):
        emit({"ok": False, "error": "Batch halted by early stop; no further dispatch."}, 1)
    path = d / "expanded" / (re.sub(r"[^A-Za-z0-9_.-]", "_", opt["item_id"]) + ".md")
    write_text(path, expand_item(read_text(d / "template.md"), matches[0]))
    emit({"ok": True, "brief_path": str(path), "template_hash": b["template_hash"],
          "pilot": opt["item_id"] in (b.get("pilot_items") or [])})


def is_failure(m):
    return m.get("completed_at") is not None and (m.get("status") not in TERMINAL_OK or m.get("failure_reason"))


def cmd_batch_status(opt):
    need(opt, "batch-id")
    root = opt.get("runs_dir")
    b = load_batch(root, opt["batch_id"])
    runs = batch_runs(root, b["batch_id"])
    done = [m for m in runs if m.get("completed_at") is not None]
    running = len(runs) - len(done)
    window = runs[:min(EARLY_STOP_WINDOW, b["item_count"])]
    win_fail = sum(1 for m in window if is_failure(m))
    limit = (EARLY_STOP_RATE * min(EARLY_STOP_WINDOW, b["item_count"])) // 1
    halt = win_fail > limit
    if halt and not b.get("halted"):
        b["halted"] = True
        save_batch(root, b)
    dispatched = {str(m.get("item_id")) for m in runs}
    items = read_json(batch_dir(root, b["batch_id"]) / "items.json")
    pending = [str(i["id"]) for i in items if str(i["id"]) not in dispatched]
    if not b.get("pilot_approved"):
        pending = [p for p in pending if p in (b.get("pilot_items") or [])]
    pilot_done = all(p in {str(m.get("item_id")) for m in done} for p in (b.get("pilot_items") or []))
    free_slots = 0 if halt else max(0, CONCURRENCY_CAP - running)
    emit({"ok": True, "batch_id": b["batch_id"], "items": b["item_count"], "dispatched": len(runs),
          "running": running, "completed": len(done),
          "succeeded": sum(1 for m in done if not is_failure(m)), "failed": sum(1 for m in done if is_failure(m)),
          "early_stop": {"window": len(window), "failures": win_fail, "max_allowed": int(limit), "halt": halt},
          "pilot_approved": bool(b.get("pilot_approved")),
          "awaiting_pilot_approval": not b.get("pilot_approved") and pilot_done,
          "free_slots": free_slots, "next_items": [] if halt else pending[:free_slots]})


def cmd_batch_approve_pilot(opt):
    need(opt, "batch-id")
    if not opt.get("confirmed_by_user"):
        emit({"ok": False, "error": "Pilot approval requires explicit user confirmation (--confirmed-by-user)."}, 2)
    root = opt.get("runs_dir")
    b = load_batch(root, opt["batch_id"])
    b["pilot_approved"] = True
    save_batch(root, b)
    a = read_json(approved_path(root), default={"entries": []})
    if b["template_hash"] not in approved_hashes(root):
        a["entries"].append({"template_hash": b["template_hash"], "batch_id": b["batch_id"], "approved_at": now_iso()})
        write_json(approved_path(root), a)
    emit({"ok": True, "batch_id": b["batch_id"], "template_hash": b["template_hash"]})


def cmd_batch_sample(opt):
    need(opt, "batch-id")
    root = opt.get("runs_dir")
    b = load_batch(root, opt["batch_id"])
    rate = float(opt.get("rate", "0.2"))
    rng = random.Random(int(opt["seed"])) if opt.get("seed") is not None else random
    runs = batch_runs(root, b["batch_id"])
    ok = [m for m in runs if not is_failure(m) and m.get("completed_at") is not None]
    must = [m for m in ok if m.get("pilot") or (m.get("files_changed") or [])]
    pool = [m for m in ok if not m.get("pilot") and not (m.get("files_changed") or [])]
    pool_ids = [m["run_id"] for m in pool]
    n = -(-int(rate * len(pool_ids))) if pool_ids else 0  # ceil
    sampled = rng.sample(pool_ids, n) if n else []
    b["sampled"] = sampled
    b["sample_rate"] = rate
    save_batch(root, b)
    emit({"ok": True, "must_check": [m["run_id"] for m in must], "sampled": sampled,
          "not_checked": [p for p in pool_ids if p not in sampled],
          "rule": "If any checked run fails its spot-check, check every run in not_checked (spec §5)."})


def cmd_batch_report(opt):
    need(opt, "batch-id")
    root = opt.get("runs_dir")
    b = load_batch(root, opt["batch_id"])
    runs = batch_runs(root, b["batch_id"])

    def reason(m):
        if m.get("completed_at") is None:
            return "still running"
        if m.get("failure_reason"):
            return m["failure_reason"]
        if m.get("status") == "blocked":
            r = read_json(run_dir(root, m["run_id"]) / "result.json") or {}
            return "blocked: " + (r.get("needed_action") or r.get("blocked_reason") or "unspecified")
        return m["status"]

    groups = {}
    for m in runs:
        groups.setdefault(reason(m), []).append(m)
    lines = [f"# Batch report: {b['batch_id']}", "", f"- Generated: {now_iso()}",
             f"- Template hash: `{b['template_hash']}`",
             f"- Items: {b['item_count']}, dispatched: {len(runs)}" + (" (HALTED by early stop)" if b.get("halted") else ""),
             f"- Spot-check sample ({b.get('sample_rate', 'n/a')}): " + (", ".join(b.get("sampled") or []) or "none"), ""]
    for g, ms in groups.items():
        lines.append(f"## {g} ({len(ms)})")
        lines.append("")
        for m in ms:
            extra = " (pilot)" if m.get("pilot") else ""
            extra += f", review: {m['review']}" if m.get("review") else ""
            lines.append(f"- `{m.get('item_id')}`: run `{m['run_id']}`{extra}")
        lines.append("")
    path = batch_dir(root, b["batch_id"]) / "report.md"
    write_text(path, "\n".join(lines))
    emit({"ok": True, "report_path": str(path),
          "groups": {g: [str(m.get("item_id")) for m in ms] for g, ms in groups.items()}})


def main():
    args = sys.argv[1:]
    if not args:
        emit({"ok": False, "error": "Usage: runlog.py <command> [options]; see module docstring."}, 2)
    opt = parse_cli(args[1:], flags=("confirmed-by-user",))
    cmds = {
        "init": cmd_init, "new-run": cmd_new_run, "record-result": cmd_record_result,
        "save-output": cmd_save_output, "set-status": cmd_set_status, "show": cmd_show, "labels": cmd_labels,
        "batch-new": cmd_batch_new, "batch-expand": cmd_batch_expand, "batch-status": cmd_batch_status,
        "batch-approve-pilot": cmd_batch_approve_pilot, "batch-sample": cmd_batch_sample,
        "batch-report": cmd_batch_report,
    }
    fn = cmds.get(args[0])
    if fn is None:
        emit({"ok": False, "error": f"Unknown command: {args[0]}"}, 2)
    fn(opt)


if __name__ == "__main__":
    main()
