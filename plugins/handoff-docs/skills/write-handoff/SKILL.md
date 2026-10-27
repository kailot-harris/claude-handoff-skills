---
name: write-handoff
description: Write or update a HANDOFF.md for a multi-session or multi-agent project so the next agent (or human) can resume work with zero prior context. Use when the user asks to "write a handoff doc", "update the handoff", "leave notes for the next session", "document where we left off", or at a natural stopping point after a chunk of real progress on a long-running project that spans multiple phases, issues, or sessions.
---

# Write Handoff

Produces a `HANDOFF.md` (or updates an existing one) at the root of the
project being worked on. The audience is a reader with **zero session
context** — a fresh agent or a human who wasn't in this conversation — who
needs to get productive on the very next task without re-deriving anything
you already figured out. Optimize for that reader, not for summarizing what
you did for the current user.

## When to use this

- The user explicitly asks for a handoff doc, session notes, or to update
  `HANDOFF.md`.
- You've just finished a meaningful chunk of work on a project that's
  clearly going to span multiple sessions/agents (tracked issues, phases or
  milestones, a long-running migration, a multi-week feature) and the user asks
  you to wrap up, or a natural stopping point is reached.
- Don't use this for a one-off task with no future continuation, or to
  replace a PR description / commit message — those serve a different
  reader (a reviewer evaluating *this* change) than a handoff doc (an agent
  who needs to *continue* the work).

## Before writing anything: gather real state, don't reconstruct from memory

A handoff doc's entire value is being *more accurate* than the reader's
assumptions. Never write a section from what you remember doing — always
re-derive it from the actual current state:

- `git log --oneline -20` and `git status` — what's actually committed,
  what's still dirty.
- The project's own issue/task tracker (e.g. `gh issue list --state all`) —
  don't trust a stale table in an old HANDOFF.md; cross-check it against
  live tracker state. If you find a discrepancy (duplicate issues, an issue
  closed that has no corresponding code, a task marked done that isn't),
  **flag it explicitly in the doc rather than silently reconciling it** —
  fixing tracker hygiene is usually outside the scope of a handoff and is a
  visible, sometimes destructive action (closing/deleting) that the project
  owner should decide on, not the doc-writer.
- Actual file contents/line counts for anything you're going to describe as
  "done" vs "stub" — `wc -l`, a quick `grep` for `TODO`/stub markers, don't
  guess.
- Test suite output, run fresh, not remembered from earlier in the session.
- If a HANDOFF.md already exists, read it fully first — you're updating it,
  not starting over, and the reader benefits from continuity (e.g. keep a
  running "gotchas discovered" list rather than dropping earlier ones).

## Structure

Adapt section names to the project, but cover these, roughly in this order.
For a filled-in example of all seven at the right level of detail, read
`reference/example-handoff.md` — copy its specificity, not its content.

1. **Header.** One line: when written, after which commit/milestone, who
   it's for ("whoever picks this up next"). This is a timestamp for
   staleness-checking, not decoration.

2. **What this project is.** A reader with zero context needs: what the
   project does, where the authoritative spec/plan/reference lives (link or
   path, and *read this before that* ordering if there are multiple
   documents), and any hard boundary rules (e.g. "the Python codebase is the
   reference implementation, don't edit it from this workstream"). Flag
   where planning docs have known-stale details (e.g. line-number citations
   that drift as source changes) so the reader doesn't trust them blindly.

3. **Progress tracking.** A table mapping task/issue IDs to status
   (closed/open, with a "next up" marker on the very next item). Include a
   commit-to-issue mapping if the project uses "Closes #N" commits. State
   *where* validation evidence lives (e.g. "read the issue comment, not just
   the commit message") rather than duplicating it here — a handoff doc
   points to evidence, it doesn't restate all of it.

4. **What's actually implemented.** The most-abused section — be concrete,
   not vibes. A table of files/components with genuine state (not "mostly
   done": real vs. stub, which specific functions exist, line counts).
   Someone should be able to `grep` for a function name from this table and
   find it. If a file is a stub with only a comment describing future work,
   say so plainly.

5. **Environment/tooling notes.** Everything a fresh session would waste
   time rediscovering: things not on `PATH` and the exact fix, package
   manager quirks specific to this project (e.g. a dependency that's
   invisible to static-analysis-based lockfile tools and needs manual
   pinning), known upstream/reference-implementation bugs that were
   deliberately *not* fixed (with why), process-management gotchas (e.g. a
   launched dev server's PID isn't the actual worker PID and killing it
   wrong leaves orphaned processes), and what's *not* configured in this
   environment (e.g. no API keys — so which validation paths were actually
   exercised live vs. only mocked). This section is where most of a
   handoff's practical time-savings comes from; don't skimp on it.

6. **The reusable workflow.** If work has followed a repeatable pattern
   (e.g. "read the spec section → re-verify line-number anchors → implement
   → test → render/run end-to-end → commit with `Closes #N`"), write it out
   as concrete, ordered steps so the next session repeats the *proven*
   process instead of reinventing one. Fold in lessons learned as sub-bullets
   on the relevant step (e.g. "this bit us on issue 7: X" belongs under the
   step where X should have been caught, not in a separate list).

7. **Concrete next step.** Not "continue with the next task" — name the
   exact next unit of work, cite the spec section, name the exact
   file(s)/function(s) to touch, flag any known architectural gotcha
   specific to it (e.g. "unlike every prior piece, X is the primary source
   here, not the fallback"), and state how it should be validated. If you
   can see two steps ahead, briefly note the one after too, so the reader
   can plan.

## Principles

- **Concrete over vague.** "Issue 5 done" tells the reader nothing
  actionable; "`parse_config()` added in `src/config.py:40-96`, handles both
  the TOML and YAML paths, validated against the fixtures in
  `tests/fixtures/config/`" does.
- **Cite exact locations, and warn they drift.** A `file:line` citation is
  accurate the day you write it and decays from there. Cite them anyway —
  they save real time — but say they should be re-verified rather than
  trusted, and anchor them to a commit where it matters.
- **Surface anomalies, don't silently fix them.** If you notice something
  wrong while gathering state for the doc (duplicate tracker issues, a
  broken cache in a dependency, stale data), write it down and leave it for
  the owner to decide — a handoff doc is not the place to take unreviewed
  corrective action.
- **Write for cold pickup.** No pronouns without antecedents from "earlier
  in this conversation" — there is no earlier conversation for the reader.
  Every acronym/internal term gets defined or pointed at its source on first
  use.
- **Don't fabricate validation evidence.** Only describe what was actually
  run and verified this session (or in the session that produced whatever
  you're updating) — if something is untested, say so, don't imply coverage
  that doesn't exist.

## If the project mirrors a reference implementation

Skip this section unless the work is a port, a rewrite, or a parity
reimplementation of something that already exists elsewhere. When it is,
these belong in the handoff:

- **Every divergence, explicitly** — whether you fixed a real bug in passing
  or deliberately preserved a quirk for parity. Both need a stated reason.
  The absence of a note reads as "this behaves identically to the
  reference," so an undocumented change in *either* direction costs the next
  person a debugging session.
- **Which version of the reference you read.** A commit SHA or release tag,
  so the reader can tell whether your citations still point at the same code.
- **The boundary rule**, if the reference is read-only from this workstream
  (e.g. "the Python codebase is the reference; don't edit it from here").
  State it in the orientation section, where a cold reader hits it early.

## After writing

Show the diff (or the new file) to confirm it reads sensibly end-to-end, not
just section-by-section. Commit it as its own commit if the project's
convention is to commit docs separately from feature work (check recent
`git log` for that project's style — e.g. a prior `docs: rewrite HANDOFF.md
for the X workstream` commit is a strong signal to follow the same pattern).
Only commit if asked to, per normal git-safety rules.

**When the doc outgrows itself:** a `HANDOFF.md` that's been updated across
many sessions accumulates writeups for work that closed long ago, until the
next-step section — the most important thing in the file — is buried at the
bottom of several hundred lines of history. Don't solve that by writing less
here. Use the companion `trim-handoff` skill, which moves closed-work
sections into an archive file and leaves pointers behind. Rough trigger: more
than half the file is about closed work.

## What this skill doesn't do

- **Not a changelog or release notes.** Those face users of the software; a
  handoff faces the next person working on it.
- **Not a PR description or commit message.** Those serve a reviewer
  evaluating *this* change. A handoff serves someone who needs to *continue*
  the work, and the two need almost opposite content.
- **Not a project spec.** If the project has an authoritative spec, the
  handoff points at it (§1) and never restates or forks it.
- **Doesn't fix what it finds.** Tracker hygiene, stale docs, duplicate
  issues — surface them in the doc, leave the decision to the owner.
- **Doesn't trim itself.** See above.
