#!/usr/bin/env python3
"""Secrets scanner for briefs (block) and logs (redact). Spec §6.

Usage:
  scan_secrets.py check FILE [FILE...]      exit 1 if any unallowlisted secret found
  scan_secrets.py redact IN [--out OUT]     write a redacted copy (default: in place)
  scan_secrets.py allow (--sha256 H | --pattern REGEX) --reason TEXT --added-by NAME --confirmed-by-user
  scan_secrets.py list-allow

Only call `allow` after the user has explicitly confirmed the entry (spec §6.1).
"""
import argparse
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import emit, now_iso, read_json, runs_dir, sha256_text, write_json  # noqa: E402

SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("webhook_url", re.compile(r"https://(?:hooks\.slack\.com/services|discord(?:app)?\.com/api/webhooks)/[^\s\"'<>]+")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("credential_assignment", re.compile(
        r"(?i)\b[A-Z0-9_]*(?:API_?KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY)[A-Z0-9_]*\s*[=:]\s*[\"']?([^\s\"']{8,})")),
]

# High-entropy check: mixed-alphabet strings only. Pure hex (git SHAs, digests),
# UUIDs and long file paths are not flagged by entropy alone; the known key
# formats above still catch real keys.
ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+/_\-=]{24,}")
ENTROPY_THRESHOLD = 4.3
HEX_OR_UUID = re.compile(r"^(?:[0-9a-fA-F]+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")


def shannon(s):
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def allowlist_path(root=None):
    return runs_dir(root) / ".secrets-allowlist"


def load_allowlist(root=None):
    data = read_json(allowlist_path(root), default={"entries": []})
    hashes = {e["sha256"] for e in data["entries"] if e.get("sha256")}
    patterns = [re.compile(e["pattern"]) for e in data["entries"] if e.get("pattern")]
    return data, hashes, patterns


def _allowed(value, hashes, patterns):
    return sha256_text(value) in hashes or any(p.fullmatch(value) for p in patterns)


def find_secrets(text, root=None):
    _, hashes, patterns = load_allowlist(root)
    findings, spans = [], []

    def add(kind, start, end):
        value = text[start:end]
        if _allowed(value, hashes, patterns):
            return
        if any(s <= end and e >= start for s, e in spans):
            return
        spans.append((start, end))
        line = text.count("\n", 0, start) + 1
        preview = value[:4] + "..." + value[-2:] if len(value) > 8 else "..."
        findings.append({"type": kind, "line": line, "start": start, "end": end,
                         "preview": preview, "sha256": sha256_text(value)})

    env_hook = os.environ.get("SUBAGENT_ALERT_WEBHOOK", "")
    if len(env_hook) >= 8:
        for m in re.finditer(re.escape(env_hook), text):
            add("alert_webhook_url", m.start(), m.end())

    for kind, rx in SECRET_PATTERNS:
        for m in rx.finditer(text):
            g = 1 if m.groups() and m.group(1) else 0
            add(kind, m.start(g), m.end(g))

    for m in ENTROPY_TOKEN.finditer(text):
        tok = m.group(0)
        if HEX_OR_UUID.match(tok):
            continue  # git SHAs, digests, UUIDs
        if tok.count("/") > 2:
            continue  # file paths
        if shannon(tok) >= ENTROPY_THRESHOLD:
            add("high_entropy", m.start(), m.end())

    return sorted(findings, key=lambda f: f["start"])


def redact_text(text, root=None):
    findings = find_secrets(text, root)
    out = text
    for f in sorted(findings, key=lambda f: f["start"], reverse=True):
        out = out[:f["start"]] + f"[REDACTED:{f['type']}]" + out[f["end"]:]
    return out, findings


def public_findings(findings):
    return [{k: v for k, v in f.items() if k not in ("start", "end")} for f in findings]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("files", nargs="+")
    r = sub.add_parser("redact"); r.add_argument("infile"); r.add_argument("--out")
    a = sub.add_parser("allow")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--sha256"); g.add_argument("--pattern")
    a.add_argument("--reason", required=True)
    a.add_argument("--added-by", required=True)
    a.add_argument("--confirmed-by-user", action="store_true")
    sub.add_parser("list-allow")
    args = ap.parse_args()

    if args.cmd == "check":
        results = {}
        for f in args.files:
            found = find_secrets(Path(f).read_text(encoding="utf-8"), args.runs_dir)
            if found:
                results[f] = public_findings(found)
        emit({"ok": not results, "findings": results}, 0 if not results else 1)

    if args.cmd == "redact":
        text = Path(args.infile).read_text(encoding="utf-8")
        out, found = redact_text(text, args.runs_dir)
        Path(args.out or args.infile).write_text(out, encoding="utf-8")
        emit({"redactions": len(found), "types": sorted({f["type"] for f in found})})

    if args.cmd == "allow":
        if not args.confirmed_by_user:
            emit({"ok": False, "error": "Allowlist entries require explicit user confirmation (--confirmed-by-user)."}, 2)
        if args.pattern:
            re.compile(args.pattern)
        data, _, _ = load_allowlist(args.runs_dir)
        entry = {"sha256": args.sha256, "pattern": args.pattern, "added_by": args.added_by,
                 "added_at": now_iso(), "reason": args.reason}
        data["entries"].append({k: v for k, v in entry.items() if v is not None})
        write_json(allowlist_path(args.runs_dir), data)
        emit({"ok": True, "entry": data["entries"][-1]})

    if args.cmd == "list-allow":
        emit(load_allowlist(args.runs_dir)[0])


if __name__ == "__main__":
    main()
