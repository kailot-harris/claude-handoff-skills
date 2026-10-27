---
template: batch
schema_version: "1.0"
---
<!-- Batch template (spec §8). Same sections as the full brief; `{{item}}` and optional `{{item_context}}` are filled per item. -->

## Goal
<!-- Outcome for a single item: {{item}} -->

## Context
{{item_context}}
<!-- Shared background for every item. -->

## Scope
Only {{item}}.

## Out of scope
Every other item in this batch, and anything not named in Scope.

## Allowed actions
- Tier 0
- Tier 1

## Success criteria
1. <criterion for {{item}}>. Verify: <command or file:line check>

## Output schema
Return exactly one JSON object matching `schema/result.v1.json` (schema_version "1.0"), in a ```json fenced block as your final message.
- `run_id`: {{run_id}}
- `item_id`: {{item_id}}
- `data`: <per-item fields, identical shape across items>

## Stop conditions
Stop and return `status: blocked` if you need an ungranted action, need to touch another item, or the item doesn't fit the template. Do not start subagents of your own.
