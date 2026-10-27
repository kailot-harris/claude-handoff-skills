---
template: full
schema_version: "1.0"
---
<!-- Full brief (spec §3.1). Every section below is required. Delete these comments before dispatch or leave them; comments are ignored by validation. -->

## Goal
<!-- One or two sentences on the outcome, not the steps. -->

## Context
<!-- What the subagent can't work out for itself: relevant files, prior decisions, constraints, conventions. -->

## Scope
<!-- Files, functions or directories the subagent may touch. -->

## Out of scope
<!-- What it must not touch or change. -->

## Allowed actions
<!-- List every tier granted, one per line; only listed tiers are allowed. Tier 0-1 is the usual default; Tier 2-3 need explicit detail.
- Tier 0
- Tier 1
- Tier 2: <what may be deleted/installed>
- Tier 3: <specific action and target, e.g. push to branch feat/x>
-->
- Tier 0
- Tier 1

## Success criteria
<!-- Numbered. Each criterion names how it is verified. -->
1. <criterion>. Verify: <command or file:line check>

## Output schema
Return exactly one JSON object matching `schema/result.v1.json` (schema_version "1.0"), in a ```json fenced block as your final message.
- `run_id`: {{run_id}}
- `criteria`: one entry per success criterion above, same ids, in order.
- `status: success` only if every criterion is `met: yes` with evidence.
- `data`: <task-specific fields, or {}>

## Stop conditions
Stop and return `status: blocked` (with `blocked_reason` and `needed_action`) if:
- You need an action not granted under Allowed actions.
- The task requires touching anything listed under Out of scope.
- The goal or scope is ambiguous enough that two reasonable readings lead to different changes.
- The task is too large to finish; suggest how to split it. Do not start subagents of your own.
Return `status: could_not_verify` if the work is done but a criterion can't be checked in this environment.
