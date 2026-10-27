#!/usr/bin/env python3
"""Validate a subagent result against its schema version and the result rules. Spec §5.

Usage:
  validate_result.py RESULT.json [--expect-run-id ID] [--expect-criteria N]

Accepts either a JSON file or raw subagent output containing one JSON object
(the last ```json fenced block is used if the whole text isn't JSON).
Exit 0 = valid, 1 = invalid (treat as failed: schema_violation; do not retry).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SCHEMA_DIR, emit  # noqa: E402

TYPES = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}


def load_schema(version):
    major = str(version).split(".")[0]
    path = SCHEMA_DIR / f"result.v{major}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _type_ok(value, t):
    ts = t if isinstance(t, list) else [t]
    for name in ts:
        py = TYPES[name]
        if name == "integer" and isinstance(value, bool):
            continue
        if isinstance(value, py):
            return True
    return False


def schema_errors(value, schema, path="$"):
    """Built-in JSON Schema subset: type, enum, required, properties,
    additionalProperties=false, items, minLength, maxLength. No external
    dependency (no jsonschema package needed)."""
    errs = []
    if "type" in schema and not _type_ok(value, schema["type"]):
        return [f"{path}: expected {schema['type']}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}: missing required `{k}`")
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                errs += schema_errors(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected property `{k}`")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errs += schema_errors(v, schema["items"], f"{path}[{i}]")
    return errs


def extract_json(text):
    # Defensive BOM strip: _common.read_text already handles files on disk
    # via utf-8-sig, but this function is also called on text captured other
    # ways (subagent stdout, piped input), so strip a leading BOM here too.
    text = text.lstrip("﻿")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.findall(r"```(?:json)?\s*\n(.*?)\n```", text, re.S)
    for block in reversed(fenced):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    return None


def rule_errors(r, expect_run_id=None, expect_criteria=None):
    errs = []
    ev_ids = [e["id"] for e in r.get("evidence", [])]
    if len(set(ev_ids)) != len(ev_ids):
        errs.append("Evidence ids must be unique.")
    for c in r.get("criteria", []):
        for ref in c.get("evidence_refs", []):
            if ref not in ev_ids:
                errs.append(f"Criterion {c['id']} references unknown evidence `{ref}`.")
    status = r.get("status")
    if status == "success":
        if not r.get("criteria"):
            errs.append("`success` requires at least one criterion.")
        for c in r.get("criteria", []):
            if c["met"] != "yes":
                errs.append(f"`success` but criterion {c['id']} is `{c['met']}`.")
            if not c.get("evidence_refs"):
                errs.append(f"`success` but criterion {c['id']} has no evidence.")
    if status == "could_not_verify" and not any(c["met"] == "unverified" for c in r.get("criteria", [])):
        errs.append("`could_not_verify` requires at least one criterion with met=`unverified`.")
    if status == "blocked" and not r.get("blocked_reason"):
        errs.append("`blocked` requires `blocked_reason`.")
    if status != "blocked" and r.get("needed_action"):
        errs.append("`needed_action` is only valid when status is `blocked`.")
    if expect_run_id and r.get("run_id") != expect_run_id:
        errs.append(f"run_id `{r.get('run_id')}` does not match dispatched run `{expect_run_id}`.")
    if expect_criteria is not None and len(r.get("criteria", [])) != expect_criteria:
        errs.append(f"Brief has {expect_criteria} criteria but result reports {len(r.get('criteria', []))}.")
    return errs


def validate(text, expect_run_id=None, expect_criteria=None):
    obj = extract_json(text)
    if obj is None:
        return {"valid": False, "errors": ["No parseable JSON object found in output."],
                "failure_reason": "schema_violation"}
    if not isinstance(obj, dict):
        return {"valid": False, "errors": ["Result must be a JSON object."], "failure_reason": "schema_violation"}
    version = obj.get("schema_version")
    schema = load_schema(version) if version else None
    if schema is None:
        return {"valid": False, "errors": [f"Unknown schema_version `{version}`."], "failure_reason": "schema_violation"}
    errs = schema_errors(obj, schema)
    if not errs:
        errs = rule_errors(obj, expect_run_id, expect_criteria)
    out = {"valid": not errs, "errors": errs, "schema_version": version, "status": obj.get("status"), "result": obj}
    if errs:
        out["failure_reason"] = "schema_violation"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("--expect-run-id")
    ap.add_argument("--expect-criteria", type=int)
    args = ap.parse_args()
    report = validate(Path(args.result).read_text(encoding="utf-8"), args.expect_run_id, args.expect_criteria)
    out = {k: v for k, v in report.items() if k != "result"}
    emit(out, 0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
