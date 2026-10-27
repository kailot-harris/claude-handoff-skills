"""Shared helpers for subagent-brief scripts. Python 3 standard library only —
no pip installs, no project runtime required. This is the skill's own
implementation language; it has nothing to do with the host repo's language."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SCHEMA_DIR = SKILL_DIR / "schema"
DEFAULT_RUNS_DIR = ".subagent-runs"


def runs_dir(path=None):
    if path:
        return Path(path)
    env = os.environ.get("SUBAGENT_RUNS_DIR", "")
    return Path(env) if env else Path(DEFAULT_RUNS_DIR)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path):
    # utf-8-sig transparently strips a leading UTF-8 BOM if present, and
    # behaves exactly like utf-8 otherwise. Files saved on Windows by
    # PowerShell's `ConvertTo-Json | Out-File` (or `Set-Content -Encoding
    # utf8` on older PowerShell) carry a BOM that plain utf-8 decoding leaves
    # in the string, breaking json.loads on an otherwise-valid file.
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def write_text(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    tmp.replace(p)


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    write_text(path, json.dumps(obj, indent=2, sort_keys=False) + "\n")


def emit(obj, code=0):
    """Print a JSON report to stdout and exit with `code`. Every script in
    this skill follows this contract: non-zero exit means stop."""
    print(json.dumps(obj, indent=2))
    sys.exit(code)


def dir_size(path):
    p = Path(path)
    if not p.exists():
        return 0
    if p.is_file():
        return p.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(p):
        for name in files:
            fp = os.path.join(root, name)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def parse_cli(args, flags=(), multi=()):
    """Minimal CLI parser: positional args, `--key value`, boolean `--flag`s,
    and `--multi val val val` (collects until the next `--option`)."""
    flags = {f.replace("-", "_") for f in flags}
    multi = {m.replace("-", "_") for m in multi}
    out = {".pos": []}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:].replace("-", "_")
            if key in flags:
                out[key] = True
            elif key in multi:
                vals = []
                while i + 1 < len(args) and not args[i + 1].startswith("--"):
                    vals.append(args[i + 1])
                    i += 1
                out[key] = vals
            else:
                if i + 1 >= len(args):
                    emit({"ok": False, "error": f"Missing value for {a}"}, 2)
                out[key] = args[i + 1]
                i += 1
        else:
            out[".pos"].append(a)
        i += 1
    return out
