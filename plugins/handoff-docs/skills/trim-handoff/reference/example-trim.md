# Trimming a HANDOFF.md — worked example

A compressed before/after for one trim pass, showing how the Step 2
classification plays out in practice. The project is fictional
(`ledger-sync`, a CLI that syncs bank transactions into SQLite).

---

## Before — `HANDOFF.md`, 840 lines

```
§1  Header (last updated, current commit, next up)          12 lines
§2  What this project is                                    35 lines
§3  Progress tracking table                                 40 lines
§4  Issue 14 — schema design notes (pre-implementation)     90 lines
§5  Issue 14 — what was built                               70 lines
§6  Issue 15 — API client, full bisection of the auth bug  145 lines
§7  Issue 16 — parser writeup                               85 lines
§8  Issue 17 — dedup: design interview notes                60 lines
§9  Issue 17 — dedup: shipped summary                       30 lines
§10 Issue 18 — full-refresh sync writeup + live transcript 115 lines
§11 What's actually implemented (file table)                45 lines
§12 Environment and tooling notes                           50 lines
§13 Commit-to-issue hash mapping                            25 lines
§14 The reusable workflow                                   30 lines
§15 Concrete next step (issue 19)                            8 lines
```

Issues 14–18 are all closed. Roughly 600 of 840 lines describe finished
work, and the single most important section — §15, the next step — is the
shortest thing in the file and sits at the very bottom. That's the signal to
trim.

## Classification

| Section | Verdict | Why |
|---|---|---|
| §1 Header | **Keep** | Staleness anchor. Update the date. |
| §2 What this is | **Keep** | Orientation; a cold reader needs it. |
| §3 Progress table | **Keep, trimmed** | Open items in full; closed items collapse to status + one-line result. |
| §4 Issue 14 design notes | **Archive** | Superseded by §5. Note that in the archive entry. |
| §5 Issue 14 writeup | **Archive** | Closed work, no bearing on what's next. |
| §6 Issue 15 auth bisection | **Archive** | Pure "how a past bug was diagnosed." |
| §7 Issue 16 parser writeup | **Archive** | Closed. |
| §8 Issue 17 interview notes | **Archive** | Pre-implementation, shipped. Point at §9's summary. |
| §9 Issue 17 shipped summary | **Archive** | Closed, and §11 already records the resulting state. |
| §10 Issue 18 writeup | **Condense** | Most recent work. Keep ~15 lines (what shipped + the one reusable gotcha); archive the live transcript. |
| §11 Implemented inventory | **Keep** | Current state. The reason the doc exists. |
| §12 Environment notes | **Keep** | Still live. Check none were superseded by a later fix. |
| §13 Hash mapping | **Cut** | Recoverable via `git log --grep "Closes #N"`. Don't even archive. |
| §14 Reusable workflow | **Keep** | Governs future work. |
| §15 Next step | **Keep** | Never dilute this one. |

Note §10: it's closed work, which argues for archiving, but it's also the
most recent thing anyone did and the gotcha it found is likely to recur.
Condensing beats archiving outright. When torn, keep.

## After — `HANDOFF.md`, 215 lines

```
§1 Header (updated date, note that a trim happened)
§2 What this project is
§3 Progress tracking (open in full, closed collapsed)
§4 See archive/handoff_history.md §4 for the full issue-14 writeup.
§5 See archive/handoff_history.md §6 for the full issue-15 writeup.
§6 See archive/handoff_history.md §7 for the full issue-16 writeup.
§7 See archive/handoff_history.md §8 for the full issue-17 writeup.
§8 Issue 18 — full-refresh sync (15-line summary + pointer to §10)
§9 What's actually implemented
§10 Environment and tooling notes
§11 The reusable workflow
§12 Concrete next step (issue 19)
```

Sections renumbered; the pointers use the path chosen in Step 3. Every
cross-reference elsewhere in the doc that said "see §12" for the environment
notes now says "see §10."

## After — `archive/handoff_history.md`

```markdown
# HANDOFF archive — ledger-sync

Non-load-bearing history. Nothing here describes current state — for that,
read HANDOFF.md. Section numbers below are the originals from HANDOFF.md at
the time each batch was moved; they are historical and are NOT synced to the
live doc's numbering, so that old commit messages and issue comments citing
them still match.

## Batch moved 2026-03-14 (from HANDOFF.md at commit a3f91c2)

### §4 Issue 14 — schema design notes
> Superseded by §5 below, which describes what actually shipped.

[original content, verbatim]

### §5 Issue 14 — what was built
[original content, verbatim]

...
```

## Verification

The archive file is new here, so `git diff` alone would show nothing. Either
`git add -N archive/handoff_history.md` first, or check directly: every
heading removed from `HANDOFF.md` (§4–§10, §13) appears in the archive except
§13, which was deliberately cut — and that exception is worth stating to the
user explicitly rather than letting them notice a gap later.

Report: 840 → 215 lines, 600 lines archived, 25 cut as recoverable from git.
