# HANDOFF.md — worked example

This is an illustrative `HANDOFF.md` for a fictional project, showing the
seven sections from `SKILL.md` filled in at the right level of detail. Copy
the *shape* and the *specificity*, not the content. Section names should be
adapted to the project.

The project here: `ledger-sync`, a CLI that pulls transactions from a bank
API into a local SQLite database.

---

## Header

> **Last updated:** 2026-03-14, after commit `a3f91c2` (issue 18 closed).
> **For:** whoever picks this up next — agent or human, no prior context assumed.
> **Next up:** issue 19, incremental sync. See §7.

Short, and every line earns its place. The date and commit let a reader check
staleness in one glance; without them they can't tell if this doc describes
reality.

## 1. What this project is

`ledger-sync` pulls transactions from the Acme Bank API and writes them into
a local SQLite file (`~/.ledger/ledger.db`). It is a one-way sync: nothing is
ever written back to the API.

Read in this order:

1. `docs/spec.md` — the authoritative behavior spec. Section numbers here
   refer to it.
2. `docs/schema.sql` — the database schema, with comments explaining the
   non-obvious columns.
3. This file.

**Boundary rule:** `vendor/acme-sdk/` is vendored upstream code. Don't edit
it — if it needs a fix, patch at the call site in `src/client.py` and note it
in §5.

**Known-stale:** `docs/spec.md` §4 cites line numbers in `src/client.py` that
have drifted since it was written. Treat them as hints, re-verify before
relying on them.

## 2. Progress tracking

| Issue | Title | Status | Evidence |
|---|---|---|---|
| 14 | Schema + migrations | Closed | `docs/schema.sql`, tests in `tests/test_schema.py` |
| 15 | API client + auth | Closed | Validation transcript in issue 15 comment |
| 16 | Transaction parser | Closed | `tests/test_parser.py`, 41 cases |
| 17 | Dedup on `(account_id, txn_id)` | Closed | See issue 17 comment, not the commit message |
| 18 | Full-refresh sync | Closed | `a3f91c2`; ran live against sandbox, 1,204 rows |
| 19 | **Incremental sync** | **Open — next up** | — |
| 20 | Retry/backoff | Open | — |

Commits use `Closes #N`, so `git log --grep "Closes #17"` finds the work for
any closed issue.

Validation evidence lives in the issue comments, not here — this table points
at it rather than restating it.

## 3. What's actually implemented

| File | Lines | State |
|---|---|---|
| `src/client.py` | 310 | Real. `fetch_page()`, `authenticate()`, `_refresh_token()`. Pagination works; no retry logic yet (issue 20). |
| `src/parser.py` | 188 | Real. `parse_txn()`, `normalize_amount()`. Handles all five transaction types in spec §3. |
| `src/db.py` | 240 | Real. `upsert_txns()`, `migrate()`. Dedup is enforced by a UNIQUE index, not application code. |
| `src/sync.py` | 95 | **Partial.** `full_refresh()` works. `incremental()` exists but is a stub — a docstring and `raise NotImplementedError`. That's issue 19. |
| `src/cli.py` | 120 | Real. `sync`, `status`, `migrate` subcommands wired up. |

Any function named above can be found with `grep -rn "def <name>" src/`.

## 4. Environment and tooling notes

This section saves the most time. Be exhaustive.

- **`ACME_API_KEY` is not set in this environment.** Everything against the
  live API was run with the sandbox key in `.env.example`. The production
  code path (`client.py:88`, the `_prod_base_url` branch) has **never been
  exercised live** — only unit-tested with mocks.
- **`sqlite3` CLI is not on PATH** in the devcontainer. Use
  `python -m sqlite3` or install it with `apt-get install sqlite3`.
- **`vendor/acme-sdk` is invisible to `pip-compile`.** It's vendored, not a
  declared dependency, so lockfile regeneration silently drops nothing but
  also won't flag it. If you bump Python versions, check it manually.
- **Upstream bug deliberately not fixed:** `acme-sdk` returns `amount` as a
  string for refunds and a float for everything else. We normalize in
  `parser.normalize_amount()` rather than patching the SDK, so the vendored
  copy stays a clean upstream mirror.
- **Killing a running sync:** `ledger-sync sync` forks a worker. The PID
  printed to stdout is the parent; `kill`ing it leaves the worker orphaned
  holding the SQLite write lock. Use `ledger-sync status --kill` instead.

## 5. The reusable workflow

Every closed issue above followed this, and it works:

1. Read the relevant `docs/spec.md` section end to end.
2. Re-verify any line numbers the spec cites — they drift.
3. Write the failing test first, in `tests/test_<module>.py`.
4. Implement.
5. `pytest tests/ -x` — full suite, not just the new file.
   - *This bit us on issue 16:* the parser change broke a dedup test in a
     different file. Run the whole suite at step 5, not just your own tests.
6. Run end-to-end against the sandbox: `ledger-sync sync --sandbox`.
7. Commit with `Closes #N`, and paste the validation output into the issue
   comment before closing.

## 6. Open questions / anomalies

Flagged, not fixed — the owner should decide:

- Issues 22 and 25 appear to be duplicates of each other (both "add CSV
  export"). I did not close either.
- `tests/fixtures/txns_large.json` is 40 MB and committed to the repo. It
  predates me. Probably wants to be generated or LFS'd, but that's a call for
  the owner.

## 7. Concrete next step

**Issue 19 — incremental sync.** Spec §5.2.

Replace the stub at `src/sync.py:71` (`incremental()`). It should:

- Read the high-water mark from the `sync_state` table (`db.py:201`,
  `get_watermark()` — already written and tested, just unused).
- Pass it as the `since` parameter to `client.fetch_page()`.
- Upsert through the existing `db.upsert_txns()`; dedup is handled by the
  UNIQUE index, so you don't need to check for existing rows.

**Gotcha specific to this one:** unlike `full_refresh()`, which can assume an
empty table, incremental runs against live data — and the Acme API's `since`
filter is *inclusive*, so the last already-synced transaction comes back
every run. The dedup index absorbs it, but any row count you log will be off
by one unless you account for it. Spec §5.2 is wrong about this; it says
exclusive. Verified against the sandbox on 2026-03-14.

**Validate by:** running `ledger-sync sync --sandbox` twice in a row. The
second run should insert 0 new rows and exit clean.

**Two steps ahead:** issue 20 (retry/backoff) touches the same
`client.fetch_page()` call path, so if you're already in there, it may be
worth reading spec §6 before you start.
