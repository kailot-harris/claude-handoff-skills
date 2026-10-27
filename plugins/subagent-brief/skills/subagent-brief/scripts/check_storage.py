#!/usr/bin/env python3
"""Storage milestones, alerts and pruning plan. Spec §7.3, §7.4.

Usage:
  check_storage.py [--older-than-days 30]
  check_storage.py prune --runs ID [ID...] --confirmed-by-user

`check` measures the run log plus kept worktrees. For each milestone
(1 GB, 10 GB, 100 GB, ...) crossed and not yet alerted it POSTs to the webhook
in SUBAGENT_ALERT_WEBHOOK (stdlib urllib, no curl dependency) and returns
`notify_in_app: true` so the orchestrator sends a push notification. Nothing
is deleted by `check`.
"""
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import dir_size, emit, now_iso, parse_cli, read_json, runs_dir, write_json  # noqa: E402
from cleanup_worktrees import kept_worktree_paths  # noqa: E402

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


def state_path(root):
    return runs_dir(root) / "storage-state.json"


def human_bytes(b):
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = min(len(units) - 1, int(math.log(b, 1000))) if b > 0 else 0
    return f"{b / 1000 ** i:.1f} {units[i]}"


def post_webhook(url, payload):
    """Deliver the payload with urllib; the URL is never written to any file
    or printed, only used as the request target."""
    if not url:
        return {"delivered": False, "skipped": True, "error": "SUBAGENT_ALERT_WEBHOOK not set"}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, OSError):
        code = None
    ok = code is not None and 200 <= code < 300
    return {"delivered": ok, "skipped": False, "http_status": code,
            "error": None if ok else "webhook delivery failed; milestone will be retried next run"}


def pruning_plan(root, older_than_days):
    base = runs_dir(root)
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    old = []
    if base.exists():
        for d in base.iterdir():
            m = read_json(d / "meta.json") if d.is_dir() else None
            if not m:
                continue
            try:
                t = datetime.strptime(m["created_at"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except (KeyError, ValueError):
                continue
            if t < cutoff:
                old.append({"run_id": m["run_id"], "created_at": m["created_at"], "status": m.get("status"),
                           "bytes": dir_size(base / m["run_id"])})
    return old


def cmd_check(opt):
    root = opt.get("runs_dir")
    base_unit = float(opt.get("milestone_base", "1e9"))  # override only for testing
    days = float(opt.get("older_than_days", "30"))
    log_bytes = dir_size(runs_dir(root))
    wt = kept_worktree_paths(root)
    wt_bytes = sum(dir_size(p) for p in wt)
    total = log_bytes + wt_bytes

    state = read_json(state_path(root), default={"alerted": []})
    alerted = set(state.get("alerted") or [])
    crossed = {base_unit * (10 ** k) for k in range(0, int(math.floor(math.log10(total / base_unit))) + 1)} if total >= base_unit else set()
    new = sorted(crossed - alerted)

    webhook = None
    plan = []
    message = None
    if new:
        plan = pruning_plan(root, days)
        top = max(new)
        message = (f"subagent-brief: run storage passed {human_bytes(top)} (now {human_bytes(total)}: "
                   f"logs {human_bytes(log_bytes)}, kept worktrees {human_bytes(wt_bytes)}). "
                   f"{len(plan)} run(s) older than {days:g} days are candidates for pruning; "
                   f"nothing is deleted without confirmation.")
        payload = {"content": message, "text": message, "milestone_bytes": top, "total_bytes": total,
                   "path": str(runs_dir(root).resolve()) if runs_dir(root).exists() else str(runs_dir(root)),
                   "pruning_plan": [{"run_id": p["run_id"], "bytes": p["bytes"]} for p in plan]}
        webhook = post_webhook(os.environ.get("SUBAGENT_ALERT_WEBHOOK", ""), payload)
        if webhook["delivered"] or webhook["skipped"]:
            state["alerted"] = sorted(alerted | set(new))
            state["last_alert_at"] = now_iso()
            runs_dir(root).mkdir(parents=True, exist_ok=True)
            write_json(state_path(root), state)

    emit({"ok": True, "total_bytes": total, "log_bytes": log_bytes, "kept_worktree_bytes": wt_bytes,
          "total_human": human_bytes(total), "new_milestones": new, "notify_in_app": len(new) > 0,
          "message": message, "webhook": webhook, "pruning_plan": plan})


def cmd_prune(opt):
    if not opt.get("confirmed_by_user"):
        emit({"ok": False, "error": "Pruning requires explicit user confirmation (--confirmed-by-user)."}, 2)
    if not opt.get("runs"):
        emit({"ok": False, "error": "--runs ID [ID...] is required."}, 2)
    root = opt.get("runs_dir")
    removed, missing = [], []
    for run_id in opt["runs"]:
        base = os.path.basename(run_id)
        d = runs_dir(root) / base
        if RUN_ID_RE.match(base) and (d / "meta.json").exists():
            import shutil
            shutil.rmtree(d)
            removed.append(run_id)
        else:
            missing.append(run_id)
    emit({"ok": not missing, "removed": removed, "not_found": missing}, 1 if missing else 0)


def main():
    args = sys.argv[1:]
    if args and args[0] == "prune":
        cmd_prune(parse_cli(args[1:], flags=("confirmed-by-user",), multi=("runs",)))
    cmd_check(parse_cli(args[1:] if args and args[0] == "check" else args))


if __name__ == "__main__":
    main()
