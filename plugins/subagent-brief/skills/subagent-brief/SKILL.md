---
name: subagent-brief
description: Write rigorous, repeatable briefs for subagents and verify what comes back. Use whenever delegating work to a subagent — a single task (implement, fix, refactor), a batch of near-identical tasks across many files or items, or a read-only lookup. Enforces a fixed brief template, risk-tier grants, worktree isolation for writers, a strict JSON result schema with evidence, secrets scanning, pilot + early stop for batches, and an auditable run log.
---

# Subagent Brief

Every delegation goes through this skill. Scripts are Python 3 (standard library only — no pip installs, nothing to add to the host project) and print JSON; a non-zero exit means **stop**. This is the skill's own implementation language, independent of whatever language the project is in — it runs the same way in a Python, JS, Go, R, or any other repo.

Full rationale: `spec.md` (if shipped alongside). The rules below are binding.

## Prerequisites

- **Python 3.8+** and **`git`**. Nothing else — no pip installs, no project dependency file to touch.
- **`$PY` in the commands below is your Python command.** It is `python3` on macOS and Linux. On **Windows it is `python` or `py -3`** — `python3` is usually not a real command there, and Windows ships an App Execution Alias of that name that opens the Microsoft Store instead of running anything. Check once with `python --version` before the first dispatch and use whatever works for the rest of the session.
- **`$SKILL` is this skill's own directory.** All script paths below are relative to it.
- Run scripts from the **project root**, so `.subagent-runs/` lands there rather than inside the skill.

`runlog.py` adds a `/.subagent-runs/` entry (with a comment) to the project's root `.gitignore` the first time it runs there — via `init`, or via `new-run` / `batch-new` if `init` was skipped. It is idempotent and never duplicates the entry, but it *is* a real change to the user's repo, so say so the first time it happens in a project.

## Hard rules

1. **No brief, no dispatch.** Every subagent gets a brief built from `templates/`, validated by `scripts/validate_brief.py`, and registered with `scripts/runlog.py new-run`. Send the subagent the contents of the `brief_path` it returns, verbatim.
2. **No nesting.** Tell subagents they must not start their own subagents (the templates already say so).
3. **Grants are explicit.** Only tiers listed under `## Allowed actions` are allowed. Tier 3 must name the action and target. A subagent that needs more returns `blocked`; you never widen its grant mid-run.
4. **Writers are isolated.** Any subagent with Tier ≥ 1 runs in its own git worktree (use the Agent tool's `isolation: "worktree"` or `git worktree add`). Lite (read-only) subagents may use the main tree.
5. **No automatic retries.** Any non-`success` result is escalated to the user. A re-run is a *new* dispatch with an amended brief, never a resumed subagent.
6. **Secrets block.** If validation reports secrets, do not dispatch and do not redact — show the user the findings. Only add an allowlist entry after the user confirms it (`scan_secrets.py allow ... --confirmed-by-user`).
7. **Nothing is deleted without the user.** Pruning runs, removing kept worktrees, and approving pilots all require `--confirmed-by-user`, which you pass only after the user said yes in this conversation.

## Choosing a template

| Situation | Template |
|---|---|
| One task that may edit files or take actions | `templates/full.md` |
| Read-only research / lookup | `templates/lite.md` (Tier 0 only) |
| Same task over N items (files, modules, series…) | `templates/batch.md` + items JSON |

Fill every section; delete or ignore the `<!-- -->` guidance. Each success criterion ends with `Verify: <command or file:line>`. Leave `{{run_id}}`, `{{item_id}}`, `{{item}}`, `{{item_context}}` for the scripts to fill.

## Single task (full or lite)

```bash
$PY $SKILL/scripts/runlog.py init                                   # once per project; adds .gitignore entry
$PY $SKILL/scripts/validate_brief.py brief.md                       # fix all errors; review warnings
$PY $SKILL/scripts/runlog.py new-run --brief brief.md --model <model> [--label issue11] [--worktree <path>]
#   -> dispatch the subagent with the returned brief_path contents
#   -> save the subagent's final message to a file, then:
$PY $SKILL/scripts/runlog.py record-result --run-id <id> --result out.txt
```

**Labels:** pass `--label <text>` on `new-run` (e.g. `--label issue11`, `--label phase1`) and use `--label` instead of `--run-id` on `record-result`, `save-output`, `set-status` and `show` from then on. This exists because usage data showed every project hand-naming files alongside the run log (`brief_issue11.md`, `result_p9a.json`, ...) since the generated run_id is opaque — use `--label` instead of inventing a parallel naming scheme. `runlog.py labels` lists everything registered. A batch item's `item_id` works as a label automatically, with no `--label` needed.

`record-result` redacts secrets, truncates long evidence (full text kept under `outputs/`), validates against the schema, and checks run_id and criteria count. Exit 1 ⇒ `failed: schema_violation` ⇒ escalate.

Then **verify before accepting** (spec §5):
- For every criterion marked `met: yes`, re-run at least one cited command or re-read at least one cited `file:line` yourself.
- If evidence doesn't support the claim: `runlog.py set-status --run-id <id> --status evidence_mismatch --reason "..."` and escalate.
- Otherwise review the worktree diff, merge, and `set-status --status merged` (or `verified` for read-only).
- On `failed` / `blocked` / `could_not_verify`: keep the worktree (`cleanup_worktrees.py keep --path <wt> --run-id <id> --reason <status>`) and report to the user with `blocked_reason` / `needed_action`.

## Batch

```bash
$PY $SKILL/scripts/validate_brief.py template.md --items items.json
$PY $SKILL/scripts/runlog.py batch-new --template template.md --items items.json
```
`items.json`: `[{"id": "f01", "item": "src/f01.ext", "context": "optional"}, ...]`.

Loop:
1. `runlog.py batch-status --batch-id <b>` → gives `next_items` (never more than the **fixed cap of 4** running) and the early-stop verdict.
2. For each item in `next_items`: `runlog.py batch-expand --batch-id <b> --item-id <i>`, then `new-run --brief <expanded> --batch-id <b> --item-id <i>`, dispatch, `record-result`.
3. **Pilot:** a template not seen before runs only its 1–2 pilot items first. When `awaiting_pilot_approval` is true, show the user the pilot results and ask. On yes: `batch-approve-pilot --batch-id <b> --confirmed-by-user` (this also records the template hash so an identical template skips the pilot next time). **Batches under 5 items skip the pilot entirely** (`batch-new`'s `pilot_required: false` with a `pilot_skip_reason`) — a batch that small dispatches in full anyway, and early stop halts on the first failure.
4. **Early stop:** if `early_stop.halt` is true (> 20% of the first 10 items failed), stop dispatching and go to the report.
5. Repeat until no `next_items` and nothing is running.

After the batch:
- `runlog.py batch-sample --batch-id <b>` → fully spot-check every run in `must_check` (pilot items and any run that changed files) and every run in `sampled` (~20% of read-only runs). If any check fails, check all of `not_checked` too.
- **Merge** worktrees one at a time, in item order. On a merge conflict: don't resolve it; `set-status --status merge_conflict`, keep the worktree, list it for the user.
- `runlog.py batch-report --batch-id <b>` → writes `report.md` with results grouped by failure reason. Give the user that summary.

## Storage and cleanup

Run `$PY $SKILL/scripts/check_storage.py` at the end of every session that used this skill. It measures the run log plus kept worktrees and, when a milestone (1 GB, 10 GB, 100 GB…) is newly crossed:
- POSTs to the webhook in `SUBAGENT_ALERT_WEBHOOK` (generic JSON with both `content` and `text`, so Discord and Slack incoming webhooks both work as-is). Never write that URL into a brief or log.
- Returns `notify_in_app: true` and a `message` → send it as a push notification, and show the user the `pruning_plan`.

Only after the user approves specific runs: `check_storage.py prune --runs <id> ... --confirmed-by-user`. Kept worktrees: `cleanup_worktrees.py list`, and on request `cleanup_worktrees.py remove (--path P | --all) --confirmed-by-user`.

## Script reference

| Script | Purpose |
|---|---|
| `validate_brief.py` | Required sections, tier grants, criteria wording, placeholders, secrets; batch items |
| `validate_result.py` | Schema (by `schema_version`) + result rules; standalone check of any output |
| `runlog.py` | Run IDs, labels, run log, result recording, batch pilot / cap / early stop / sampling / report |
| `scan_secrets.py` | `check` (block), `redact` (logs), `allow` / `list-allow` (confirmed allowlist) |
| `check_storage.py` | Milestone alerts, webhook, pruning plan; `prune` with confirmation |
| `cleanup_worktrees.py` | Registry of kept worktrees; `remove` with confirmation |

Tests: `$PY $SKILL/tests/run_tests.py` (needs git; no curl, no pip installs — the webhook path uses urllib).

## Schema versions

`schema/result.v<N>.json` is kept for every version ever shipped so old runs stay replayable. To add v2: add `result.v2.json`, keep v1, update the templates' `schema_version`. Cross-version comparisons use shared fields only and are approximate.
