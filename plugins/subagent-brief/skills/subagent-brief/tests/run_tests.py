#!/usr/bin/env python3
"""End-to-end tests for the subagent-brief scripts. Run from anywhere:
  python3 subagent-brief/tests/run_tests.py
Uses a throwaway git repo in a temp dir; needs git and python3 only (no curl,
no pip installs — the webhook path uses urllib so it's exercised offline too).
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
S = HERE.parent.parent / "scripts"

def _force_remove(func, path, _exc):
    # Windows marks git object files read-only, which makes shutil.rmtree fail
    # with PermissionError. Clear the flag and retry so a second test run in the
    # same temp dir doesn't need manual cleanup.
    os.chmod(path, stat.S_IWRITE)
    func(path)


work = Path(tempfile.gettempdir()) / "sb-test-py"
if work.exists():
    if sys.version_info >= (3, 12):
        shutil.rmtree(work, onexc=_force_remove)
    else:
        shutil.rmtree(work, onerror=_force_remove)
work.mkdir(parents=True)
os.chdir(work)
subprocess.run(["git", "init", "-q", "."], check=True)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok    {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


def run(script, *args, env=None):
    cmd = [sys.executable, str(S / script), *args]
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
        for k, v in env.items():
            if v == "":
                full_env.pop(k, None)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=full_env)
    try:
        j = json.loads(proc.stdout)
    except json.JSONDecodeError:
        j = {".raw": proc.stdout + proc.stderr}
    return proc.returncode, j


def w(path, lines):
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def brief(extra_criteria="", tiers="- Tier 0\n- Tier 1", template="full"):
    lines = ["---", f"template: {template}", 'schema_version: "1.0"', "---",
             "## Goal", "Add `fetch_totals()` returning monthly totals.",
             "## Context", "The API client lives in `src/client.ext`.",
             "## Scope", "`src/totals.ext` and its test.",
             "## Out of scope", "`src/main.ext`."]
    if template != "lite":
        lines += ["## Allowed actions", tiers]
    lines += ["## Success criteria", "1. Tests pass. Verify: `pytest tests/`"]
    if extra_criteria:
        lines.append(extra_criteria)
    lines += ["## Output schema", "Result v1 JSON, run_id {{run_id}}.",
              "## Stop conditions", "Stop if network access is needed."]
    return lines


def result(run_id, status="success", met="yes", excerpt="[ PASS 3 ]", files=None, item=None):
    if files is None:
        files = ["src/totals.ext"]
    obj = {
        "schema_version": "1.0", "run_id": run_id, "item_id": item, "status": status,
        "summary": "ok",
        "criteria": [{"id": 1, "text": "tests pass", "met": met, "evidence_refs": ["e1"]}],
        "evidence": [{"id": "e1", "type": "test_output", "ref": "pytest", "excerpt": excerpt}],
        "blocked_reason": "need push" if status == "blocked" else None,
        "needed_action": "Tier 3: push" if status == "blocked" else None,
        "changes": {"worktree": None, "files_changed": files},
        "data": {},
    }
    return "Done.\n```json\n" + json.dumps(obj) + "\n```\n"


print("validate_brief")
w("good.md", brief())
rc, j = run("validate_brief.py", "good.md")
check("valid full brief passes", rc == 0 and j.get("ok") is True)

w("t3.md", brief(tiers="- Tier 0\n- Tier 3"))
rc, j = run("validate_brief.py", "t3.md")
check("bare Tier 3 grant rejected", rc == 1)

w("t3ok.md", brief(tiers="- Tier 0\n- Tier 3: push to branch feat/totals"))
rc, j = run("validate_brief.py", "t3ok.md")
check("specific Tier 3 grant accepted", rc == 0)

w("vague.md", brief(extra_criteria="2. Code is clean."))
rc, j = run("validate_brief.py", "vague.md")
check("vague criterion warns but passes", rc == 0 and len(j.get("warnings", [])) == 2)

w("missing.md", "\n".join(brief()).replace("## Stop conditions", "## Notes"))
rc, j = run("validate_brief.py", "missing.md")
check("missing section rejected", rc == 1)

w("lite_bad.md", brief(template="lite") + ["## Allowed actions", "- Tier 1"])
rc, j = run("validate_brief.py", "lite_bad.md")
check("lite brief with Tier 1 rejected", rc == 1)

w("lite.md", brief(template="lite"))
rc, j = run("validate_brief.py", "lite.md")
check("lite brief passes", rc == 0)

rc, j = run("validate_brief.py", str(S.parent / "templates" / "full.md"))
check("unfilled template rejected (placeholders)", rc == 1 and any("placeholder" in e for e in j.get("errors", [])))

w("secret.md", brief() + ["Use ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwx"])
rc, j = run("validate_brief.py", "secret.md")
check("secret in brief blocks dispatch", rc == 1 and len(j.get("secrets", [])) >= 1)

print("secrets allowlist")
w("fixture.md", brief() + ["Fixture token: Zx9Qp2Lm7Rt4Vw8Ks1Nb6Hy3Jd5Fg0"])
rc, j = run("scan_secrets.py", "check", "fixture.md")
h = next(iter(j["findings"].values()))[0]["sha256"]
check("high-entropy fixture flagged", rc == 1)
rc, j = run("scan_secrets.py", "allow", "--sha256", h, "--reason", "test fixture", "--added-by", "tester")
check("allow without confirmation refused", rc == 2)
rc, j = run("scan_secrets.py", "allow", "--sha256", h, "--reason", "test fixture", "--added-by", "tester", "--confirmed-by-user")
check("allow with confirmation recorded", rc == 0 and j["entry"]["added_by"] == "tester")
rc, j = run("scan_secrets.py", "check", "fixture.md")
check("allowlisted value no longer flagged", rc == 0)

print("runlog: single run")
rc, j = run("runlog.py", "init")
check("init adds .gitignore entry", any(line.strip() == "/.subagent-runs/" for line in Path(".gitignore").read_text().splitlines()))
rc, j = run("runlog.py", "new-run", "--brief", "secret.md")
check("new-run blocks secret brief", rc == 1)
rc, j = run("runlog.py", "new-run", "--brief", "good.md", "--model", "test-model")
run_id = j["run_id"]
check("new-run creates run", rc == 0 and (Path(".subagent-runs") / run_id / "brief.md").exists())
check("run_id filled into brief", run_id in (Path(".subagent-runs") / run_id / "brief.md").read_text())

long_excerpt = ("x" * 3000) + " token=sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZZZZZ"
Path("res.txt").write_text(result(run_id, excerpt=long_excerpt), encoding="utf-8")
rc, j = run("runlog.py", "record-result", "--run-id", run_id, "--result", "res.txt")
check("valid result recorded", rc == 0 and j["status"] == "success")
saved = json.loads((Path(".subagent-runs") / run_id / "result.json").read_text())
check("long excerpt truncated to 2 KB", len(saved["evidence"][0]["excerpt"]) <= 2048 and saved["evidence"][0].get("full_output_path"))
full = (Path(".subagent-runs") / run_id / saved["evidence"][0]["full_output_path"]).read_text()
check("secret redacted in logged output", "sk-ant-" not in full and "REDACTED" in full)
meta = json.loads((Path(".subagent-runs") / run_id / "meta.json").read_text())
check("meta records model and redaction", meta["model"] == "test-model" and len(meta["redactions"]) == 1)
check("data {} round-trips as object", '"data": {}' in (Path(".subagent-runs") / run_id / "result.json").read_text())

rc, j = run("runlog.py", "new-run", "--brief", "good.md")
id2 = j["run_id"]
Path("bad.txt").write_text(result(id2, met="no"), encoding="utf-8")
rc, j = run("runlog.py", "record-result", "--run-id", id2, "--result", "bad.txt")
check("success with unmet criterion -> schema_violation", rc == 1 and j["failure_reason"] == "schema_violation")
check("raw output kept for failed parse", (Path(".subagent-runs") / id2 / "raw_output.txt").exists())

rc, j = run("runlog.py", "new-run", "--brief", "good.md")
id3 = j["run_id"]
Path("wrongid.txt").write_text(result("not-the-run"), encoding="utf-8")
rc, j = run("runlog.py", "record-result", "--run-id", id3, "--result", "wrongid.txt")
check("mismatched run_id rejected", rc == 1)

# Real-world bug (found via a shared usage-data sample from a Windows
# session): PowerShell's `ConvertTo-Json | Out-File` writes a UTF-8 BOM,
# which plain utf-8 decoding leaves in the string and breaks json.loads on
# an otherwise-valid result.
rc, j = run("runlog.py", "new-run", "--brief", "good.md")
id_bom = j["run_id"]
with open("bom.txt", "wb") as f:
    f.write(b"\xef\xbb\xbf" + result(id_bom).encode("utf-8"))
rc, j = run("runlog.py", "record-result", "--run-id", id_bom, "--result", "bom.txt")
check("UTF-8 BOM in result file does not break parsing", rc == 0 and j["status"] == "success")

rc, j = run("runlog.py", "set-status", "--run-id", run_id, "--status", "evidence_mismatch", "--reason", "test did not run")
check("evidence_mismatch marks run failed", j["status"] == "failed")

print("runlog: batch")
tmpl = ["---", "template: batch", 'schema_version: "1.0"', "---",
        "## Goal", "Audit {{item}} for hard-coded series IDs.",
        "## Context", "Series IDs belong in `config.yml`. {{item_context}}",
        "## Scope", "Only {{item}}.", "## Out of scope", "Other files.",
        "## Allowed actions", "- Tier 0",
        "## Success criteria", "1. No hard-coded IDs remain in {{item}}. Verify: `grep -n 'CPIAUCSL' {{item}}`",
        "## Output schema", "Result v1, run_id {{run_id}}, item_id {{item_id}}.",
        "## Stop conditions", "Stop if the file is missing."]
w("tmpl.md", tmpl)
items = [{"id": f"f{n:02d}.ext", "item": f"src/f{n:02d}.ext"} for n in range(1, 13)]
Path("items.json").write_text(json.dumps(items), encoding="utf-8")
rc, j = run("validate_brief.py", "tmpl.md", "--items", "items.json")
check("batch template + items validate", rc == 0 and j["item_count"] == 12)

rc, j = run("runlog.py", "batch-new", "--template", "tmpl.md", "--items", "items.json")
b = j["batch_id"]
check("new template requires pilot of 2", j["pilot_required"] is True and len(j["pilot_items"]) == 2)
rc, j = run("runlog.py", "batch-expand", "--batch-id", b, "--item-id", "f05.ext")
check("non-pilot item blocked before approval", rc == 1)


def dispatch(item, outcome="success"):
    rc, e = run("runlog.py", "batch-expand", "--batch-id", b, "--item-id", item)
    rc, n = run("runlog.py", "new-run", "--brief", e["brief_path"], "--batch-id", b, "--item-id", item)
    met = "yes" if outcome == "success" else "no"
    Path("item_res.txt").write_text(result(n["run_id"], status=outcome, met=met, files=[], item=item), encoding="utf-8")
    run("runlog.py", "record-result", "--run-id", n["run_id"], "--result", "item_res.txt")
    return n["run_id"]


p1 = dispatch("f01.ext")
p2 = dispatch("f02.ext")
rc, j = run("runlog.py", "batch-status", "--batch-id", b)
check("awaiting pilot approval after pilot completes", j["awaiting_pilot_approval"] is True and len(j["next_items"]) == 0)
rc, j = run("runlog.py", "batch-approve-pilot", "--batch-id", b)
check("pilot approval needs confirmation", rc == 2)
rc, j = run("runlog.py", "batch-approve-pilot", "--batch-id", b, "--confirmed-by-user")
check("pilot approved", rc == 0)
rc, j = run("runlog.py", "batch-status", "--batch-id", b)
check("concurrency cap of 4 on next_items", j["free_slots"] == 4 and len(j["next_items"]) == 4)
dispatch("f03.ext", "failed")
dispatch("f04.ext", "failed")
rc, j = run("runlog.py", "batch-status", "--batch-id", b)
check("2/10 failures does not halt", not j["early_stop"]["halt"])
dispatch("f05.ext", "failed")
rc, j = run("runlog.py", "batch-status", "--batch-id", b)
check("3/10 failures halts (>20%)", j["early_stop"]["halt"] is True and j["free_slots"] == 0)
rc, j = run("runlog.py", "batch-expand", "--batch-id", b, "--item-id", "f06.ext")
check("halted batch refuses dispatch", rc == 1)
rc, j = run("runlog.py", "batch-sample", "--batch-id", b, "--seed", "1")
check("pilot runs are always checked", all(x in j["must_check"] for x in (p1, p2)))
rc, j = run("runlog.py", "batch-report", "--batch-id", b)
check("report groups failures", rc == 0 and len(j["groups"]["failed"]) == 3 and Path(j["report_path"]).exists())

rc, j = run("runlog.py", "batch-new", "--template", "tmpl.md", "--items", "items.json")
check("approved template hash skips pilot", j["pilot_required"] is False)

print("runlog: small batch skips pilot (spec 12.1)")
small_tmpl = ["---", "template: batch", 'schema_version: "1.0"', "---",
              "## Goal", "Audit {{item}}.", "## Context", "{{item_context}}",
              "## Scope", "Only {{item}}.", "## Out of scope", "Other files.",
              "## Allowed actions", "- Tier 0",
              "## Success criteria", "1. OK. Verify: `true`",
              "## Output schema", "Result v1, run_id {{run_id}}, item_id {{item_id}}.",
              "## Stop conditions", "Stop if missing."]
w("small_tmpl.md", small_tmpl)
small_items = [{"id": f"s{n}", "item": f"src/s{n}.ext", "context": f"Context for s{n}."} for n in range(1, 4)]
Path("small_items.json").write_text(json.dumps(small_items), encoding="utf-8")
rc, j = run("runlog.py", "batch-new", "--template", "small_tmpl.md", "--items", "small_items.json")
sb = j["batch_id"]
check("batch below BATCH_PILOT_MIN_ITEMS skips pilot", j["pilot_required"] is False and j["pilot_skip_reason"])
rc, j = run("runlog.py", "batch-expand", "--batch-id", sb, "--item-id", "s2")
check("non-first item dispatchable immediately, no pilot gate", rc == 0)

print("runlog: labels (spec 12.1)")
rc, j = run("runlog.py", "new-run", "--brief", "good.md", "--label", "issue11")
id_lbl = j["run_id"]
check("new-run accepts --label and echoes it back", rc == 0 and j["label"] == "issue11")
Path("res_lbl.txt").write_text(result(id_lbl), encoding="utf-8")
rc, j = run("runlog.py", "record-result", "--label", "issue11", "--result", "res_lbl.txt")
check("record-result resolves --label to the right run", rc == 0 and j["run_id"] == id_lbl and j["status"] == "success")
rc, j = run("runlog.py", "show", "--label", "issue11")
check("show --label returns the same run's meta", rc == 0 and j["meta"]["run_id"] == id_lbl)
rc, j = run("runlog.py", "show", "--label", "no-such-label")
check("unknown label is a clean error, not a crash", rc == 2)
rc, j = run("runlog.py", "labels")
check("labels command lists registered labels", rc == 0 and j["labels"].get("issue11") == [id_lbl])
# A batch item's own item_id works as a label with no --label needed.
rc, j = run("runlog.py", "batch-expand", "--batch-id", sb, "--item-id", "s1")
rc, n = run("runlog.py", "new-run", "--brief", j["brief_path"], "--batch-id", sb, "--item-id", "s1")
rc, j = run("runlog.py", "show", "--label", "s1")
check("batch item_id is usable as a label automatically", rc == 0 and j["meta"]["run_id"] == n["run_id"])

print("worktrees + storage")
subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
subprocess.run(["git", "worktree", "add", "-q", "../sb-wt-py", "-b", "wt-test-py"], check=True)
wt = str(Path("../sb-wt-py").resolve())
Path(wt, "big.txt").write_text("y" * 5000, encoding="utf-8")
rc, j = run("cleanup_worktrees.py", "keep", "--path", wt, "--run-id", id2, "--reason", "failed")
check("worktree kept", rc == 0)
rc, j = run("check_storage.py", "--milestone-base", "1000", env={"SUBAGENT_ALERT_WEBHOOK": ""})
check("milestones crossed, in-app notify, webhook skipped",
      len(j["new_milestones"]) >= 1 and j["notify_in_app"] is True and j["webhook"]["skipped"] is True)
check("kept worktree counted in total", j["kept_worktree_bytes"] >= 5000)
rc, j = run("check_storage.py", "--milestone-base", "1000", env={"SUBAGENT_ALERT_WEBHOOK": ""})
check("same milestone not re-alerted", len(j["new_milestones"]) == 0)
(Path(".subagent-runs") / "storage-state.json").unlink()
rc, j = run("check_storage.py", "--milestone-base", "1000", env={"SUBAGENT_ALERT_WEBHOOK": "http://127.0.0.1:9/hook"})
check("failed webhook not marked alerted", j["webhook"]["delivered"] is False and not (Path(".subagent-runs") / "storage-state.json").exists())
rc, j = run("check_storage.py", "--older-than-days", "-1", "--milestone-base", "1000", env={"SUBAGENT_ALERT_WEBHOOK": ""})
check("pruning plan lists old runs", len(j["pruning_plan"]) >= 1)
rc, j = run("check_storage.py", "prune", "--runs", id3)
check("prune requires confirmation", rc == 2)
rc, j = run("check_storage.py", "prune", "--runs", id3, "--confirmed-by-user")
check("prune removes confirmed run", rc == 0 and not (Path(".subagent-runs") / id3).exists())
rc, j = run("cleanup_worktrees.py", "remove", "--all")
check("worktree removal needs confirmation", rc == 2)
rc, j = run("cleanup_worktrees.py", "remove", "--all", "--confirmed-by-user")
check("kept worktree removed", rc == 0 and not Path(wt).exists())

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
