#!/usr/bin/env python3
"""Registry and cleanup for worktrees kept after failed/blocked/conflicting runs. Spec §4.1.

Usage:
  cleanup_worktrees.py keep --path P --run-id ID --reason TEXT
  cleanup_worktrees.py list
  cleanup_worktrees.py remove (--path P | --all) --confirmed-by-user

Kept worktrees are never removed automatically. Only run `remove` after the
user has asked for cleanup.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import dir_size, emit, now_iso, parse_cli, read_json, runs_dir, write_json  # noqa: E402


def registry_path(root=None):
    return runs_dir(root) / "kept-worktrees.json"


def load_registry(root=None):
    return read_json(registry_path(root), default={"entries": []})


def kept_worktree_paths(root=None):
    return [e["path"] for e in load_registry(root)["entries"]]


def main():
    args = sys.argv[1:]
    if not args:
        emit({"ok": False, "error": "Usage: cleanup_worktrees.py keep|list|remove ..."}, 2)
    opt = parse_cli(args[1:], flags=("all", "confirmed-by-user"))
    root = opt.get("runs_dir")
    reg = load_registry(root)

    if args[0] == "keep":
        for k in ("path", "run_id", "reason"):
            if opt.get(k) is None:
                emit({"ok": False, "error": f"--{k.replace('_', '-')} is required."}, 2)
        p = str(Path(opt["path"]).resolve())
        reg["entries"] = [e for e in reg["entries"] if e["path"] != p]
        reg["entries"].append({"path": p, "run_id": opt["run_id"], "reason": opt["reason"], "kept_at": now_iso()})
        runs_dir(root).mkdir(parents=True, exist_ok=True)
        write_json(registry_path(root), reg)
        emit({"ok": True, "kept": len(reg["entries"])})

    if args[0] == "list":
        entries = [{**e, "exists": Path(e["path"]).is_dir(), "bytes": dir_size(e["path"])} for e in reg["entries"]]
        emit({"ok": True, "entries": entries, "total_bytes": sum(e["bytes"] for e in entries)})

    if args[0] == "remove":
        if not opt.get("confirmed_by_user"):
            emit({"ok": False, "error": "Removing kept worktrees requires explicit user confirmation (--confirmed-by-user)."}, 2)
        known = kept_worktree_paths(root)
        if opt.get("all"):
            targets = known
        else:
            p = str(Path(opt.get("path", "")).resolve()) if opt.get("path") else None
            targets = [p] if p in known else []
        if not targets:
            emit({"ok": False, "error": "No matching kept worktree in the registry."}, 1)
        results = []
        for p in targets:
            if Path(p).is_dir():
                proc = subprocess.run(["git", "worktree", "remove", "--force", p], capture_output=True, text=True)
                ok = proc.returncode == 0
                msg = (proc.stdout + proc.stderr).strip()
            else:
                ok, msg = True, "(already gone)"
            if ok:
                reg["entries"] = [e for e in reg["entries"] if e["path"] != p]
            results.append({"path": p, "removed": ok, "message": msg})
        write_json(registry_path(root), reg)
        all_ok = all(r["removed"] for r in results)
        emit({"ok": all_ok, "results": results}, 0 if all_ok else 1)

    emit({"ok": False, "error": f"Unknown command: {args[0]}"}, 2)


if __name__ == "__main__":
    main()
