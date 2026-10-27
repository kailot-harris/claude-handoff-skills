---
template: lite
schema_version: "1.0"
---
<!-- Lite brief (spec §3.2): read-only research. No Allowed actions section; Tier 0 only. -->

## Goal
<!-- The question to answer. -->

## Context
<!-- What is already known, where to look. -->

## Scope
<!-- Files, directories or sources to search. -->

## Out of scope
<!-- What not to investigate. -->

## Success criteria
1. <criterion>. Verify: <file:line citation or command output>

## Output schema
Return exactly one JSON object matching `schema/result.v1.json` (schema_version "1.0"), in a ```json fenced block as your final message.
- `run_id`: {{run_id}}
- `changes`: `{"worktree": null, "files_changed": []}`
- `data`: <findings structure, or {}>

## Stop conditions
This is a read-only task. If answering it needs any write, install, or outward-facing action, stop and return `status: blocked` with `needed_action`. Do not start subagents of your own.
