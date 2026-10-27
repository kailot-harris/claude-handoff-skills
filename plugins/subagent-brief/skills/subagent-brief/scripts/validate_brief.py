#!/usr/bin/env python3
"""Validate a brief before dispatch. Spec §3.3.

Usage:
  validate_brief.py BRIEF.md                     validate a full or lite brief
  validate_brief.py TEMPLATE.md --items ITEMS.json
                                                 validate a batch template and every expanded item

ITEMS.json is a list of {"id": "...", "item": "...", "context": "..." (optional)}.
Exit 0 = ok (warnings allowed), 1 = errors (do not dispatch).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SCHEMA_DIR, emit, read_json, sha256_text  # noqa: E402
from scan_secrets import find_secrets, public_findings  # noqa: E402

FULL_SECTIONS = ["Goal", "Context", "Scope", "Out of scope", "Allowed actions",
                 "Success criteria", "Output schema", "Stop conditions"]
LITE_SECTIONS = [s for s in FULL_SECTIONS if s != "Allowed actions"]
SUPPORTED_SCHEMAS = sorted(
    m.group(1) + ".0" for m in (re.match(r"result\.v(\d+)\.json$", p.name) for p in SCHEMA_DIR.glob("result.v*.json")) if m
)
VAGUE = re.compile(r"(?i)\b(works? well|is clean|looks good|properly|reasonable|as needed|"
                   r"appropriate(?:ly)?|robust|nice|better|good enough|etc\.?)\b")
TIER_LINE = re.compile(r"^\s*[-*]\s*Tier\s*([0-3])\s*(?::\s*(.*))?$", re.I)
CRITERION = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")


def parse_brief(text):
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip("\"'")
        body = m.group(2)
    sections, current = {}, None
    for line in body.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            current = h.group(1).strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return meta, {k: "\n".join(v).strip() for k, v in sections.items()}


def strip_comments(s):
    return re.sub(r"<!--.*?-->", "", s, flags=re.S).strip()


def validate_text(text, expect_template=None):
    errors, warnings = [], []
    meta, sections = parse_brief(text)
    template = meta.get("template")
    if template not in ("full", "lite", "batch"):
        return {"errors": ["Front matter must set `template: full | lite | batch`."], "warnings": warnings,
                "template": template}
    if expect_template and template != expect_template:
        errors.append(f"Expected template `{expect_template}`, got `{template}`.")
    schema = meta.get("schema_version")
    if schema not in SUPPORTED_SCHEMAS:
        errors.append(f"schema_version `{schema}` is not supported (have {SUPPORTED_SCHEMAS}).")

    required = LITE_SECTIONS if template == "lite" else FULL_SECTIONS
    for name in required:
        if not strip_comments(sections.get(name, "")):
            errors.append(f"Missing or empty required section: `## {name}`.")

    # Allowed actions / risk tiers (spec §4.2). A brief is granted exactly the
    # tiers it lists — a brief listing only `- Tier 0` is read-only.
    tiers = {0: None}
    tier_lines = 0
    actions = strip_comments(sections.get("Allowed actions", ""))
    action_lines = actions.splitlines()
    for line in action_lines:
        m = TIER_LINE.match(line)
        if m:
            tiers[int(m.group(1))] = (m.group(2) or "").strip() or None
            tier_lines += 1
    if template == "lite":
        if any(t > 0 for t in tiers):
            errors.append("Lite briefs are read-only: only Tier 0 is allowed.")
    else:
        if action_lines and any(l.strip() for l in action_lines) and tier_lines == 0:
            errors.append("`## Allowed actions` must list grants as `- Tier N[: detail]` lines.")
        if 3 in tiers and not tiers[3]:
            errors.append("Tier 3 grants must name the specific action and target, e.g. `- Tier 3: push to branch feat/x`.")
        if 2 in tiers and not tiers[2]:
            warnings.append("Tier 2 grant has no detail; consider naming what may be deleted or installed.")

    # Success criteria
    crit_text = strip_comments(sections.get("Success criteria", ""))
    crit_lines = [CRITERION.match(l) for l in crit_text.splitlines()]
    crits = [m for m in crit_lines if m]
    if not crits and crit_text:
        errors.append("`## Success criteria` must be a numbered list (`1. ...`).")
    for m in crits:
        n, body = m.group(1), m.group(2)
        if not re.search(r"(?i)\bverify\s*:", body):
            warnings.append(f"Criterion {n} does not say how it is verified (add `Verify: ...`).")
        v = VAGUE.search(body)
        if v:
            warnings.append(f"Criterion {n} uses vague wording: `{v.group(0)}`.")

    # Unfilled template placeholders. {{run_id}}/{{item_id}} are filled at
    # dispatch, {{item}}/{{item_context}} per batch item.
    visible = strip_comments(re.sub(r"(?s)^---\n.*?\n---\n?", "", text))
    visible = re.sub(r"(?s)```.*?```|`[^`\n]*`", "", visible)
    angle = re.findall(r"<[A-Za-z][^<>\n]{0,60}>", visible)
    curly = set(re.findall(r"\{\{[^}]+\}\}", visible))
    curly -= {"{{run_id}}", "{{item_id}}"} | ({"{{item}}", "{{item_context}}"} if template == "batch" else set())
    for ph in dict.fromkeys(list(angle) + sorted(curly)):
        errors.append(f"Unfilled placeholder: `{ph}`.")

    return {"errors": errors, "warnings": warnings, "template": template,
            "schema_version": schema, "tiers": sorted(tiers), "criteria_count": len(crits)}


def expand_item(template_text, item):
    out = template_text.replace("{{item}}", str(item["item"]))
    return out.replace("{{item_context}}", str(item.get("context", "")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("brief")
    ap.add_argument("--items")
    ap.add_argument("--runs-dir")
    args = ap.parse_args()

    text = Path(args.brief).read_text(encoding="utf-8")
    report = validate_text(text)
    report["template_hash"] = sha256_text(text)
    secrets = find_secrets(text, args.runs_dir)
    if secrets:
        report["errors"].append(f"Secrets scan found {len(secrets)} possible secret(s); dispatch blocked (spec §6.1).")
        report["secrets"] = public_findings(secrets)

    if report.get("template") == "batch":
        if "{{item}}" not in text:
            report["errors"].append("Batch templates must contain `{{item}}`.")
        if not args.items:
            report["errors"].append("Batch templates require --items ITEMS.json.")
        else:
            items = json.loads(Path(args.items).read_text(encoding="utf-8"))
            ids = [i.get("id") for i in items]
            if len(set(ids)) != len(ids) or None in ids:
                report["errors"].append("Every item needs a unique `id`.")
            bad = {}
            for it in items:
                exp = expand_item(text, it)
                sub = validate_text(exp, expect_template="batch")
                found = find_secrets(exp, args.runs_dir)
                errs = sub["errors"] + ([f"{len(found)} possible secret(s)"] if found else [])
                if errs:
                    bad[str(it.get("id"))] = errs
            if bad:
                report["errors"].append(f"{len(bad)} expanded item(s) failed validation.")
                report["item_errors"] = bad
            report["item_count"] = len(items)
    elif args.items:
        report["errors"].append("--items is only valid with `template: batch`.")

    report["ok"] = not report["errors"]
    emit(report, 0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
