# claude-handoff-skills

Skills for work that outlives a single Claude Code session.

Long-running projects lose more time to *re-deriving context* than to writing
code. A new session doesn't know what's already built, which tracker items are
real, or which gotcha cost someone an afternoon last week. These skills exist
to make that knowledge survive the end of a session — and, in the case of
`subagent-brief`, to make delegated work verifiable rather than merely finished.

Two plugins, three skills. Install either one independently.

| Plugin | Skills | Dependencies |
|---|---|---|
| **handoff-docs** | `write-handoff`, `trim-handoff` | None — markdown only |
| **subagent-brief** | `subagent-brief` | Python 3.8+ and `git` (standard library only) |

## Install

```
/plugin marketplace add kailot-harris/claude-handoff-skills
```

Then `/plugin install handoff-docs` or `/plugin install subagent-brief`, or
pick them from the `/plugin` menu.

To update later: `/plugin marketplace update claude-handoff-skills`.

### Without plugins

The skills are plain directories. Copy whichever you want into
`~/.claude/skills/` (or a project's `.claude/skills/`) and restart Claude Code:

```bash
git clone https://github.com/kailot-harris/claude-handoff-skills
cp -r claude-handoff-skills/plugins/handoff-docs/skills/* ~/.claude/skills/
```

You lose the update path, but nothing else.

---

## handoff-docs

### `write-handoff`

Produces or updates a `HANDOFF.md` aimed at a reader with **zero session
context** — a fresh agent or a human who wasn't in the conversation.

The central rule is that it never writes a section from memory. Before
drafting, it re-derives state from the things that can't lie: `git log` and
`git status`, the live issue tracker, actual file contents and line counts,
and a fresh test run. A handoff doc's whole value is being more accurate than
the reader's assumptions, and a doc written from recollection isn't.

It covers seven sections — orientation, progress tracking, what's genuinely
implemented (real vs. stub, not "mostly done"), environment gotchas, the
proven workflow, and a concrete next step naming exact files and validation.
`reference/example-handoff.md` shows all seven filled in.

Two behaviors worth knowing before you run it:

- **It surfaces anomalies instead of fixing them.** If it finds duplicate
  tracker issues or an issue closed with no corresponding code, it writes that
  down and leaves the decision to you. Closing or deleting things is visible
  and sometimes destructive; a doc-writing pass is the wrong place for it.
- **It won't claim validation that didn't happen.** Untested is recorded as
  untested.

**Triggers on:** "write a handoff doc", "update the handoff", "leave notes for
the next session", "document where we left off", or a natural stopping point
in a long-running project.

### `trim-handoff`

The release valve. A `HANDOFF.md` updated across many sessions accumulates
postmortems for work that closed long ago, until the next-step section — the
most important thing in the file — sits at the bottom of several hundred lines
of history.

`trim-handoff` classifies every section as keep, condense, or archive against
one question: *does a fresh reader need this to decide and start the next unit
of work?* Archived sections move **verbatim** into an archive file with a
one-line pointer left behind. Nothing is deleted, and the skill verifies
nothing was lost before the trim is final.

It works on any `HANDOFF.md`, not only one `write-handoff` produced — it
assumes only that the file has headings. `reference/example-trim.md` walks
through an 840 → 215 line pass.

**Triggers on:** "trim the handoff", "shrink HANDOFF.md", "archive old handoff
sections", or a `HANDOFF.md` that's gotten too long to navigate.

---

## subagent-brief

For delegating work to subagents when you need to trust the result.

The problem it solves: a subagent reports success, and you have no
cheap way to tell whether it actually succeeded, quietly did something
adjacent, or wrote a plausible summary of work it didn't finish.

The approach is to make both sides of the exchange structured. Every
delegation gets a brief built from a fixed template, with success criteria
that each end in `Verify: <command or file:line>`. Every result comes back as
JSON against a versioned schema, carrying evidence for each criterion. Then
you re-run at least one cited command yourself before accepting — the skill
treats unverified evidence as a failure state (`evidence_mismatch`), not a
formality.

Around that core:

- **Explicit risk tiers.** A subagent is granted exactly the tiers its brief
  lists; Tier 3 must name the action and target. One that needs more returns
  `blocked` rather than improvising, and you never widen a grant mid-run.
- **Worktree isolation** for anything that writes.
- **No automatic retries.** Every non-success result escalates to you. A
  re-run is a new dispatch with an amended brief.
- **Secrets scanning** before dispatch, with a confirmed allowlist.
- **Batches** get a pilot run of 1–2 items before the rest go out, a
  concurrency cap, and early stop if more than 20% of the first ten fail.
- **An auditable run log** under `.subagent-runs/`, with human-meaningful
  `--label`s rather than only opaque run IDs.

A fair amount of this is shaped by production use rather than theory — the
pilot-skip threshold for small batches, the labels feature, and a UTF-8 BOM
parsing bug all came from reviewing 87 real runs across four projects.
`spec.md` §12.1 records what that review found and what changed because of it.

### Requirements

- **Python 3.8+** and **git**. Standard library only — no pip installs, and
  nothing added to your project's dependency files.
- `$PY` in the skill's commands is your Python command: `python3` on macOS and
  Linux, **`python` or `py -3` on Windows** (`python3` is usually not a real
  command there, and Windows ships an App Execution Alias of that name that
  opens the Microsoft Store).

The skill's scripts run from your project root and write a run log to
`.subagent-runs/`. On first use in a project it adds a `/.subagent-runs/` entry
to the root `.gitignore` — idempotently, but it is a real change to your repo.

Run the test suite with `$PY tests/run_tests.py` from inside a scratch git
repo; it's 58 end-to-end tests and needs no network.

---

## Notes

These skills run shell commands to gather state — `git`, your test suite,
`gh` if the project uses it. That's deliberate and it's the point:
`write-handoff` is only useful because it reads reality instead of
summarizing a conversation. Neither handoff skill declares `allowed-tools`,
because any declaration permissive enough to let them inspect an arbitrary
project would be too broad to mean anything.

None of the three commit anything unless you ask.

## License

MIT — see [LICENSE](LICENSE).
