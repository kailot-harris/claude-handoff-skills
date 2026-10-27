---
name: trim-handoff
description: Trim a bloated HANDOFF.md by moving postmortem sections for closed issues, tasks, or phases into an archive file and leaving short pointers behind, keeping the live doc's current-state and next-step sections intact. Use when the user asks to "trim the handoff", "shrink HANDOFF.md", "archive old handoff sections", says HANDOFF.md has gotten bloated/too long/hard to navigate, or a HANDOFF.md has accumulated many sessions' worth of closed-work writeups.
---

# Trim Handoff

Companion to `write-handoff`, which ships alongside this skill. That one
grows `HANDOFF.md`; this one is the release valve — it moves the parts of a
long-lived `HANDOFF.md` that are no longer needed for *picking up new work*
into a separate archive file, without losing any information. Nothing gets
deleted, only relocated.

This skill works on any `HANDOFF.md`, whether or not `write-handoff` produced
it. It assumes only that the file is organized into sections with headings.

## When to use this

- The user explicitly asks to trim, shrink, or archive part of `HANDOFF.md`.
- `HANDOFF.md` has grown past the point where a fresh reader can quickly find
  "what do I do next" — usually a sign of several postmortems for closed work
  accumulating inline over many sessions.
- Don't use this preemptively on a short or freshly-written `HANDOFF.md` —
  only once bloat is real (a good rule of thumb: if more than half the file
  is about *closed* work, it's time).

For a compressed before/after of one full trim pass — section-by-section
classification, the rewritten pointers, and the archive preamble — read
`reference/example-trim.md`.

## Step 1 — Read the whole file first

Read `HANDOFF.md` end to end before touching anything (use `offset`/`limit`
if it doesn't fit one read). You cannot correctly classify a section without
seeing the full doc — later sections often reference earlier ones by number,
and superseded sections (e.g. a pre-implementation design spec followed later
by an "implemented" writeup of the same issue) are only obvious in context.

## Step 2 — Classify every section: keep, condense, or archive

For each section, ask: **"does a fresh reader need this to decide and start
the next unit of work?"**

**Keep in `HANDOFF.md` (don't touch):**
- The header (last-updated line, current commit, one-line pointer to what's
  next) — this is the staleness-check anchor, always keep it current.
- What-this-project-is / orientation, and pointers to the authoritative spec.
- The progress-tracking table, trimmed to open items plus a terse closed-item
  log (status + one-line result, not the full story).
- The current "what's actually implemented" inventory.
- Environment/tooling gotchas that are still live (i.e. not superseded by a
  later fix documented elsewhere in the doc — check for that before keeping
  one verbatim).
- The reusable workflow/methodology section.
- The concrete next-step section — this is the single most important section
  in the file; never let it get buried or diluted.
- Any standing architectural decision or constraint that still governs future
  work (not just explains past work).

**Archive (move verbatim, leave a one-line pointer):**
- Issue-by-issue "what was actually built" postmortems for
  **closed** work — the detailed narrative, bug bisections, live-validation
  transcripts, curl/test output. These have historical/audit value but no
  bearing on the next unit of work.
- Pre-implementation design specs / interview notes for issues that have
  since been implemented and closed — once shipped, only the *shipped*
  summary matters going forward; the design rationale is archive material.
  Note in the archive entry that it's superseded and point to wherever the
  shipped summary lives.
- Anything whose primary value is "how a past bug was diagnosed" rather than
  "what state things are in now."

**Condense (keep a short version in `HANDOFF.md`, move the long version to
the archive):**
- A recent, still-relevant implementation writeup that's genuinely long
  (deep bisection narratives, extended validation transcripts). Keep 10-20
  lines in `HANDOFF.md` — what shipped, and any *reusable* lessons (a
  platform bug, a gotcha likely to recur) — and move the full narrative to
  the archive with a pointer.
- Trivia like commit-to-issue hash mappings recoverable via
  `git log --grep` — usually just cut, don't even archive.

When in doubt, prefer keeping something in `HANDOFF.md` over archiving it —
the cost of a reader missing something vital is much higher than the cost of
one extra archived paragraph.

## Step 3 — Determine the archive file path

Default: `archive/handoff_history.md` at the project root. If the project has
its own established archive convention (an existing `archive/`, a tracked
`docs/archive/`, `ARCHIVE.md`, or similar), follow that instead.

**Run `git check-ignore -v <path>` on whatever path you pick, before writing
anything.** A `docs/` directory in particular is often a build target and
wholesale gitignored, which would make the archive untracked and invisible to
everyone but you.

If the chosen archive file already exists (from a previous trim), **append**
to it — read it first, add new sections after the existing content, don't
overwrite.

Whatever path you settle on, use that same path in the Step 5 pointers.

## Step 4 — Write the archive additions

- Preserve each archived section's original heading text and content
  near-verbatim — this is a relocation, not a rewrite. Light edits are fine
  only to fix now-dangling cross-references (e.g. "see §12 below" needs to
  become "see current `HANDOFF.md` §10" or "see §12 above" depending on where
  the referenced content ended up).
- Give the archive file (or the newly appended block, if appending) a short
  preamble noting when this batch was moved and that it's non-load-bearing
  history — so a future reader immediately knows not to search here for
  current state.
- Keep the original section numbers/titles in the archive even though they
  no longer match `HANDOFF.md`'s renumbered sections — old commit messages
  and issue comments may cite them, and an exact match makes them
  grep-able. Note in the archive preamble that numbers are historical, not
  synced to the live doc.

## Step 5 — Rewrite HANDOFF.md

- Replace each archived section with a single-line pointer that uses the
  archive path chosen in Step 3 — don't hardcode a path here:
  `See <archive-path> §N for the full <issue/task> writeup.`
  So with the default path, that reads:
  `See archive/handoff_history.md §7 for the full issue-23 writeup.`
- Renumber remaining sections if the doc uses numbered headers, and fix any
  internal cross-references that pointed at a section that moved or shifted.
- Re-read the resulting `HANDOFF.md` end to end to confirm it still reads
  sensibly as a standalone document — a reader who never opens the archive
  should still get a coherent, accurate picture of current state and next
  steps.

## Step 6 — Verify nothing was lost

Confirm every archived section made it into the archive file intact before
the trimmed `HANDOFF.md` is treated as final. This is a relocation — losing
content here is worse than not trimming at all.

How you check depends on whether the archive file is new:

- **Appending to an existing, tracked archive:** `git diff` on both files
  together. Every heading and body line removed from `HANDOFF.md` should
  appear as an addition in the archive.
- **Creating the archive for the first time:** a plain `git diff` will *not*
  show it — a brand-new file is untracked and invisible to diff, so the check
  would pass while verifying nothing. Either run `git add -N <archive-path>`
  first so it shows up as an intent-to-add, or compare directly: every
  heading removed from `HANDOFF.md` is present in the archive, and the
  archive's line count is at least the number of lines removed.
- **Not a git repo at all:** compare the list of removed headings against the
  archive's headings, and spot-check the longest archived section end to end.

## After writing

Show the user a summary: original vs. new `HANDOFF.md` line count, what moved
where. Only commit if asked, per normal git-safety rules — prefer committing
the archive addition and the `HANDOFF.md` trim together in one commit (they're
one logical change), unless the project's convention (check recent `git log`)
is to separate doc changes.

## What this skill doesn't do

- **Doesn't delete anything.** Every archived section is relocated verbatim.
  The one exception is trivia that's recoverable from git (commit-to-issue
  hash mappings), and cutting it is called out to the user explicitly.
- **Doesn't rewrite or summarize archived content.** Light edits only, to fix
  cross-references that would otherwise dangle.
- **Doesn't update current state.** If the live sections are stale or wrong,
  that's `write-handoff`'s job — trimming a doc and correcting it are
  separate operations, and mixing them makes the diff impossible to review.
- **Doesn't decide the project is done with something.** Classification keys
  off work already marked closed, not off a judgement that it ought to be.
