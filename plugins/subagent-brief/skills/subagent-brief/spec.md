# Spec: Subagent Brief Skill

**Status:** Draft v0.8
**Date:** 2026-09-23 (revised 2026-10-20)
**Purpose:** Give subagents rigorous, repeatable instructions and get back results the orchestrator can verify.

---

## 1. Goals and non-goals

### Goals
- Every delegation uses a structured brief, so two runs of the same brief behave the same way.
- Every subagent returns a result the orchestrator can parse and check against evidence.
- State-changing work is safe to delegate: it is isolated, limited to granted actions, and reviewed before merge.
- Batch work (one task across N items) is cheap to abort and easy to review.
- Every run can be audited and replayed afterward.

### Non-goals
- Delegation more than one level deep (subagents do not spawn subagents).
- Per-task model selection (subagents use the orchestrator's model).
- Automatic retries (failures always escalate to the user).

---

## 2. Use cases

| # | Use case | Template | May change state | Parallel |
|---|----------|----------|------------------|----------|
| UC1 | **Single delegation**: one well-defined task, e.g. "implement X", "fix bug Y" | Full | Yes | No |
| UC2 | **Batch mode**: one template applied across N similar items, e.g. "audit these 40 files" | Full, with an item variable | Yes | Yes (capped) |
| UC3 | **Lite lookup**: read-only research or investigation | Lite | No | Optional |

---

## 3. Brief template

### 3.1 Full template (required sections)

The skill **rejects** any brief that is missing one of these sections.

| Section | Contents |
|---------|----------|
| **Goal** | One or two sentences on the outcome, not the steps. |
| **Context** | Background the subagent can't work out for itself: relevant files, prior decisions, constraints. |
| **Scope / Out-of-scope** | What the subagent may touch, and what it must not touch. |
| **Allowed actions** | An explicit grant of the risk tiers allowed (see §4.2). A brief is granted exactly the tiers it lists. |
| **Success criteria** | A numbered list of checkable criteria. Each one should state how it is verified. |
| **Output schema** | A reference to the result schema version (§5). It may add task-specific `data` fields. |
| **Stop conditions** | When to stop and report instead of continuing, e.g. an ungranted action is needed, scope is ambiguous, or a criterion can't be verified. |

### 3.2 Lite template (read-only only)

This template is for UC3. It requires **Goal, Context, Scope, Success criteria, Output schema, and Stop conditions**. It leaves out Allowed actions (fixed at Tier 0) and isolation.

- A lite brief implicitly includes this stop condition: **if the task needs any write or outward-facing action, stop and return `blocked`.**
- The subagent must not upgrade a lite brief to a full brief itself.

### 3.3 Validation
Before dispatch, the skill checks that:
1. All required sections are present and not empty.
2. Every success criterion is written as something that can be checked (warn on vague wording such as "works well" or "is clean").
3. The allowed actions are consistent with the template type.
4. The secrets scan passes (§6.1).
5. No template placeholder (`<...>`, or any `{{...}}` other than `{{run_id}}`/`{{item_id}}`/the batch item variables) is left unfilled.

A brief that fails validation is not dispatched.

---

## 4. Safety

### 4.1 Worktree isolation
- Every subagent that may write (UC1 and UC2 with Tier ≥ 1) runs in its **own git worktree**.
- The orchestrator reviews the diff and the evidence **before** merging back to the main tree.
- Lite (read-only) subagents may run in the main tree.
- Worktrees are cleaned up after merge or rejection.
- Worktrees from **failed or blocked runs, and items skipped because of merge conflicts, are kept until the user runs a cleanup command**. They are never deleted automatically after a set time. Their disk usage counts toward the storage alerts (§7.3).

### 4.2 Risk tiers

| Tier | Actions | Default |
|------|---------|---------|
| 0 | Read files, search, run read-only commands | Allowed |
| 1 | Edit and create files inside the worktree, run local builds and tests | Allowed (full template) |
| 2 | Delete files, destructive git operations inside the worktree, install dependencies | Requires a grant |
| 3 | Outward-facing or irreversible actions: push, open a PR, deploy, send messages, call external APIs that change state | Requires a grant naming the specific action |

- If a subagent needs an action it wasn't granted, it **stops and returns `blocked`** with the action it needed. It does not improvise a workaround.
- A Tier 3 grant must name the specific action and target (e.g. "push to branch `feat/x`"), not a whole category.

### 4.3 No nesting
Subagents cannot start their own subagents. If a subtask is too big, the subagent returns `blocked` and suggests how to split it.

---

## 5. Result schema

Every subagent returns JSON that matches this schema. Output that doesn't match is treated as `failed` (reason: `schema_violation`) and escalated. It is **not** retried.

```json
{
  "schema_version": "1.0",
  "run_id": "string",
  "item_id": "string | null",
  "status": "success | failed | blocked | could_not_verify",
  "summary": "string (≤ 500 chars)",
  "criteria": [
    {
      "id": 1,
      "text": "string",
      "met": "yes | no | unverified",
      "evidence_refs": ["e1", "e2"]
    }
  ],
  "evidence": [
    {
      "id": "e1",
      "type": "file_ref | command | test_output | diff | other",
      "ref": "path:line | command string",
      "excerpt": "string (≤ 2 KB; truncated with marker)"
    }
  ],
  "blocked_reason": "string | null",
  "needed_action": "string | null",
  "changes": {
    "worktree": "path | null",
    "files_changed": ["path"]
  },
  "data": {}
}
```

### Rules
- `status: success` requires **every** criterion to be `met: yes`, each with at least one piece of evidence.
- `could_not_verify` means the work was done but one or more criteria can't be checked in this environment.
- Evidence excerpts longer than 2 KB are truncated **before** schema validation, not after — truncating only on success would reject a long-but-otherwise-valid excerpt for exceeding `maxLength` before it ever gets truncated. The full output goes to the run log (§7) and is referenced by path.
- `data` holds task-specific structured output, defined by the brief's Output schema section.

### Orchestrator verification
Before merging or accepting a result, the orchestrator **spot-checks** evidence: it re-runs at least one cited command or re-reads at least one cited `file:line` for each criterion marked `met: yes`. Evidence that is present but doesn't support the claim counts as `failed`.

**Batch sampling:** in batch mode, the spot-check is sampled instead of covering every item:
- Pilot items: always fully checked.
- **Items that changed files: always fully checked before merge.**
- Remaining (read-only) items: a random sample of about 20% is fully checked. (Accepted trade-off: batches of writers pay the full N × criteria cost in checks.) The sampled item IDs are recorded in the batch report.
- If any sampled item fails its check, every remaining unchecked item is checked.

---

## 6. Secrets

### 6.1 In briefs (before dispatch)
- Scan every brief for anything that looks like a secret: known key formats (AWS, GitHub, Anthropic, and so on), private key blocks, high-entropy strings, and `KEY=`/`TOKEN=`/`PASSWORD=` assignments.
- **When the scan finds something, dispatch is blocked** and the user is asked what to do. There is no automatic redaction.
- An **allowlist** (e.g. `.subagent-runs/.secrets-allowlist`) holds patterns or hashes known to be false positives (fixtures, UUIDs, hashes).
- **Allowlist governance:** entries are added **only with explicit user confirmation**. The orchestrator may propose an entry but never adds one itself. Each entry records `pattern_or_hash`, `added_by`, `added_at`, and `reason`.

### 6.2 In logs (before they're written)
- Result JSON, evidence excerpts, and full outputs are scanned before being written to disk.
- Matches are **redacted** (`[REDACTED:<type>]`), because the subagent has already run by then. The redaction is recorded in the run metadata.

---

## 7. Run log

### 7.1 Layout
```
.subagent-runs/                 # added to .gitignore automatically
  <run_id>/
    brief.md                    # the brief exactly as dispatched
    result.json                 # schema-validated result
    meta.json                   # timestamps, model, label, schema_version, template hash, redactions, status
    outputs/                    # full command/test outputs referenced by evidence
  batches/<batch_id>/
    template.md
    items.json
    report.md                   # grouped failure report
  labels.json                   # label -> [run_id, ...] index (spec §12.1)
  kept-worktrees.json           # registry of worktrees kept after failed/blocked/conflicting runs
  .secrets-allowlist
```

- `run_id` format: `YYYYMMDD-HHMMSS-<short-hash>`.
- `meta.json` records the model used, so later comparisons are like-for-like.
- On first use the skill checks that `.subagent-runs/` is in `.gitignore` and adds it if it's missing.

### 7.2 Replay
The skill keeps a validator for **every schema version it has shipped** (`schema/result.v1.json`, `result.v2.json`, …), so old runs can always be validated and replayed. Comparing results across versions uses only the fields both versions share and is marked approximate.

Re-dispatching a saved `brief.md` produces a new run. The skill can diff the new `result.json` against the original (status, criteria, `data`) to detect drift between runs.

### 7.3 Storage alerts and pruning
- Each time the skill runs, it measures the total size of `.subagent-runs/` **plus any worktrees it has kept**.
- At each milestone crossed (**1 GB, 10 GB, 100 GB, …**) it:
  1. Shows a warning in the session.
  2. Sends a push notification in the Claude app **and** an alert to an external channel (see §7.4).
  3. Proposes a **pruning plan** (e.g. delete runs older than 30 days, or completed batches older than N days).
- **Nothing is deleted without explicit user confirmation.**
- The skill records which milestones have already triggered an alert (in `meta` at the root), so it doesn't alert twice for the same one.

### 7.4 External alert channel
- The external channel is a **generic webhook**. `check_storage.py` POSTs JSON to the URL in the environment variable `SUBAGENT_ALERT_WEBHOOK`, via the standard library's `urllib` (no `curl` dependency).
- Payload: `{"content": "...", "text": "...", "milestone_bytes": N, "total_bytes": N, "path": "...", "pruning_plan": [...]}`. `content` is what Discord reads and `text` is what Slack reads, so both work as they are.
- If the variable isn't set, the script reports the webhook as skipped and the in-app alert still fires.
- The webhook URL is a secret: it is never written to briefs, logs, or `meta.json`, and it is part of the log redaction patterns.
- A failed webhook delivery doesn't mark the milestone as alerted, so the next run tries again.

---

## 8. Batch mode

### 8.1 Flow
1. **Template:** one full brief containing an `{{item}}` variable (plus optional per-item context).
2. **Validation:** validate the template once, and scan every expanded item for secrets.
3. **Pilot:** dispatch **1–2 items** and show the user their results. **Wait for approval** before continuing.
   - **Pilot skip (template reuse):** if the template's hash exactly matches a template whose pilot the user previously approved (recorded in `batches/.approved-templates`), the pilot is skipped. The early stop (step 5) still applies.
   - **Pilot skip (small batch):** a batch with fewer than `BATCH_PILOT_MIN_ITEMS` (5) items skips the pilot outright, regardless of whether the template is new. All of its items are dispatchable immediately. This does **not** register the template hash as approved, so a later, larger batch on the same template still gets a real pilot.
4. **Dispatch:** run the remaining items with a **fixed concurrency cap of 4** (not adjustable per batch), queueing the rest.
5. **Early stop:** if **more than 20% of the first 10 items** (pilot included; the whole batch if it has fewer than 10 items) fail, halt the batch and report.
6. **Completion:** otherwise, run every item to completion.
7. **Report:** one grouped report: items that succeeded, and failures **grouped by reason** (`schema_violation`, `blocked: <action>`, `criterion N not met`, …).
8. **Merge:** see §8.2.

### 8.2 Merge strategy
- Worktrees are merged **one at a time, in item order**, after the orchestrator's review of each item passes.
- **On a conflict, the item is skipped** and never auto-resolved. Its worktree is kept and it is listed under "Merge conflicts" in the batch report for the user to resolve.
- Known trade-off: items later in the batch are more likely to conflict with changes already merged.

### 8.3 Scale notes
- Cost grows linearly with N. The pilot and early stop are the main cost controls.
- The orchestrator's context grows with N, so the orchestrator reads `summary` and `status` for each item and loads full results only for failures or spot checks.
- With a cap of 4, at most 4 worktrees exist at once.

---

## 9. Failure handling

| Situation | Behavior |
|-----------|----------|
| Output breaks the schema | Mark `failed: schema_violation`, escalate |
| `blocked` (ungranted action or ambiguity) | Escalate with `needed_action` / `blocked_reason` |
| `could_not_verify` | Escalate; the user decides whether to accept |
| Criterion not met | Mark `failed`, escalate; keep the worktree |
| Spot-check disproves evidence | Mark `failed: evidence_mismatch`, escalate |
| Secrets found in brief | Block dispatch, ask the user |

**There are no automatic retries.** A re-run is a new dispatch that the user starts, optionally with an amended brief.

**Blocked subagents are never resumed.** To fix a `blocked` result, amend the brief (e.g. add the grant) and **dispatch it again as a new run**, so every run matches exactly one saved brief. Work left in the blocked run's worktree may be carried over by naming that worktree in the new brief's Context.

---

## 10. Risks

| Risk | Mitigation |
|------|------------|
| Criteria that can't really be checked give false confidence | Validation warns on vague criteria; `could_not_verify` status; orchestrator spot-checks |
| Evidence that is real but doesn't support the claim | Orchestrator re-runs or re-reads evidence before merging |
| Broken batch template multiplies into N bad runs | Pilot + early stop at >20% of the first 10 |
| Parallel writers conflict | Worktree isolation; sequential merge, conflicting items skipped and reported |
| Secrets leak into briefs or logs | Blocking scan on briefs; redaction on logs; gitignored folder |
| Secrets allowlist grows to cover real secrets | Entries added only with user confirmation; each one records who, when, and why |
| Unbounded log/worktree growth | Milestone alerts (logs + kept worktrees) + pruning plan confirmed by the user; checked only when the skill runs |
| Schema changes break comparison with old runs | `schema_version` on every result and meta file; a validator kept for every shipped version |
| Rigid template adds overhead to small tasks | Lite template for read-only work |
| Lite task quietly needs a write | Implicit stop condition → `blocked` |

---

## 11. Open questions

_None at this time._

### Resolved
- Batch merge: sequential in item order; conflicts are skipped and reported (§8.2).
- Pilot skip: allowed when the template hash matches a previously approved pilot, or when the batch is below `BATCH_PILOT_MIN_ITEMS` (§8.1).
- Blocked follow-up: amend and dispatch again as a new run; never resume (§9).
- Concurrency cap: fixed at 4 (§8.1).

---

## 12. Packaging

```
subagent-brief/
  SKILL.md                     # when to use, the workflow, and rules for the orchestrator
  templates/
    full.md                    # full brief template (§3.1)
    lite.md                    # lite brief template (§3.2)
    batch.md                   # batch template with {{item}} / {{item_context}} (§8)
  schema/
    result.v1.json             # JSON Schema for results (§5); one file per shipped version
  scripts/                     # all run with $PY (see SKILL.md) and print JSON; non-zero exit = stop
    _common.py                 # shared helpers
    validate_brief.py          # required sections, tier grants, criteria wording, placeholders, secrets
    validate_result.py         # schema check by schema_version + result rules
    runlog.py                  # run IDs, labels, run log, result recording, batch pilot/cap/early stop/sampling/report
    scan_secrets.py            # brief scan (block), log redaction, confirmed allowlist (§6)
    check_storage.py           # logs + kept worktrees size, milestone alerts, webhook, pruning (§7.3–7.4)
    cleanup_worktrees.py       # registry and removal of kept worktrees (§4.1)
  tests/
    run_tests.py                # end-to-end tests in a throwaway git repo
```

- **Language: Python 3, standard library only.** No pip installs, no project dependency file to edit or activate. This is a deliberate change from an earlier draft that used R to match one host project — that was the wrong default for a skill meant to travel across repos, since it meant the skill's own tooling could be mistaken for (or clash with the confusion of) the project's language, and it required an R toolchain in repos that have none. Python 3 is far more commonly preinstalled, and more importantly it is not *the project's* language in any repo, R included — it is purely the skill's implementation detail. External tools: `git` only. The storage-alert webhook uses the standard library's `urllib`, not `curl`, so there is no external-binary dependency for that either.
- Validation, schema checks and secret scanning are done by **deterministic scripts**, not left to the model's reading of the prose. This supports repeatability.
- Schema validation uses a built-in checker for the JSON Schema subset the result schema uses (type, enum, required, properties, additionalProperties, items, min/maxLength), so there is no `jsonschema` package dependency.
- `runlog.py` was added during the build, so that run IDs, `meta.json`, the approved-template registry and batch state live in code rather than in the orchestrator's judgement.
- Behaviour decided during the build:
  - A full brief is granted **exactly** the tiers it lists. A brief listing only `- Tier 0` is read-only.
  - Unfilled placeholders (`<...>`, or any unknown `{{...}}`) are validation errors.
  - For early stop, any non-`success` outcome among the first 10 items counts as a failure, including `blocked` and `could_not_verify`. With fewer than 10 items, the window is the whole batch.
  - Entropy-based secret detection skips pure hex strings (git SHAs, digests), UUIDs and long file paths to limit false positives. Known key formats are still caught.
  - Evidence excerpts are truncated **before** schema validation, not after — truncating only on success would reject a long-but-otherwise-valid excerpt for exceeding `maxLength` before it ever gets truncated. This was a real bug caught by the Python port's test suite and is now how both implementations work.
- **Porting history:** this skill was first built in Python, rewritten in R to match a single host project's language, and ported back to Python — standard library only — once more than one project needed it. The R detour is the reason the language choice is argued above at the length it is: matching the host project's language looks like good citizenship and is actually the opposite, because it makes the skill's own tooling a dependency of the repo it is supposed to be portable into. An R copy of the same logic remains in the project it was written for and is not being migrated; it is expected to fall behind this spec.

### 12.1 Changes driven by real usage

The design decisions below were not reasoned from first principles — they came from reviewing the run logs (`meta.json` / `result.json`, never the brief or result *content* as instructions) of 87 real runs across four projects that had been using the skill for several weeks, in October 2026. They are recorded here because the reasoning explains behaviour that would otherwise look arbitrary.

- **A real, portable bug, now fixed:** two result files, produced on Windows (PowerShell's `ConvertTo-Json | Out-File` writes a UTF-8 BOM), failed to parse — plain `utf-8` decoding left the BOM character in the string and `json.loads` rejected an otherwise-valid file. Fixed by reading files as `utf-8-sig` (`_common.read_text`) and defensively stripping a leading BOM in `validate_result.extract_json`. Added as a regression test. This would have hit *any* language's JSON tooling reading a BOM'd file the naive way, not just this skill — but it's exactly the kind of thing that only shows up once real Windows usage exists.
- **The batch workflow was tried once and abandoned mid-flight.** One project ran `batch-new` on a 4-item batch, got `pilot_items` back, and then never called `batch-approve-pilot` — instead, the orchestrator extracted each item's `context` by hand and dispatched every item through plain `new-run` (non-batch) briefs. The batch's `items.json` and a near-identical hand-made copy sit side by side. Plausible cause: a 4-item batch is small enough that generating a pilot approval gate and tracking a `batch_id` felt like more ceremony than it was worth. **Fixed:** `BATCH_PILOT_MIN_ITEMS = 5` in `runlog.py`; a batch below that size sets `pilot_required: false` with a `pilot_skip_reason` and every item is dispatchable from the start. This does not register the template hash as approved — a later, larger batch on the same template still gets a real pilot — because a small batch finishing cleanly isn't the same evidence a 2-item pilot of a 50-item batch would be.
- **Hand-named files alongside the run log, in every single project.** Every project has proper `YYYYMMDD-HHMMSS-<hash>/` run directories *and* a parallel set of loose files directly under `.subagent-runs/` named after what a human would actually want to find later — `brief_issue11.md`, `result_p9a.json`, `brief_tier3.md` — that do not correspond to any run directory's content. The run-id naming scheme optimizes for uniqueness and collision-avoidance, not for "which GitHub issue, phase, or tier was this." People (or the orchestrating sessions on their behalf) were reconstructing a human-meaningful index on top of the opaque one rather than asking the skill for it. **Fixed:** `new-run --label <text>` stores the label in `meta.json` and registers it in `.subagent-runs/labels.json`; `record-result`, `save-output`, `set-status` and `show` all accept `--label` in place of `--run-id`, resolving to the most recently registered run under that label. `runlog.py labels` lists the index. A batch item's `item_id` is registered as a label automatically, with no `--label` needed, since it was already the human-meaningful handle.
- **A handful of abandoned `dispatched` runs** (4 of 87) that were registered but never reached `record-result` — likely sessions that ended mid-task. Not a bug, but `check_storage.py`'s pruning plan currently only looks at age, not at `status: dispatched` with no `completed_at`; it could flag these specifically since they are the cheapest and safest candidates to clean up. Not yet made.
- Otherwise, the real distribution looked healthy: of 87 runs, 75 succeeded, 4 were blocked, 3 came back `could_not_verify`, and only 1 outright failed (an `evidence_mismatch` the orchestrator caught); the risk tiers were overwhelmingly Tier 0/1 (87 and 86 runs respectively) with Tier 2 used 8 times and Tier 3 exactly once — consistent with the default-deny design doing its job rather than being routinely overridden.
