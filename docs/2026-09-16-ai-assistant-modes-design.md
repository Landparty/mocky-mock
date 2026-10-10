# AI assistant modes: hands-on, guided, hands-off

**Status:** implemented
**Date:** 2026-09-16

## The problem

The packaged Claude Code skill (`mockymock/cli/skills/mockymock/`, what
`mockymock skills install` copies out) prescribes exactly one working
style. Since the 2026-09-16 paragraph-first rewrite it tells an assistant
to narrate before and after every command, report where things stand each
loop iteration, and stop and ask at four checkpoints (overwriting a
hand-written `.cut`, choosing a `--scenarios` mode, graduating to the
whole-program pass, parking a red paragraph).

That is the right default and the wrong universal. Two populations it
fails:

- A developer who has never run mockymock against a program they didn't
  write wants *more* supervision than that — they want to see the command
  before it runs, and the `MOCK` block before it lands in the file.
- A developer who has done this twenty times and wants a suite for
  `INVUPDT.cbl` by tomorrow wants *less*. Under the current contract the
  assistant stops four times per program to ask questions nobody is there
  to answer, and a delegated run stalls on checkpoint two.

Both currently have the same workaround: say so in chat, every session,
and hope it holds. Nothing carries across sessions, nothing is written
down, and "hands-off" has no agreed meaning — in particular, no agreed
answer to *what an assistant still may not do* when nobody is watching.

## The shape

One setting, three modes, on a single axis: **how much of the workflow
comes back to the developer.** The workflow itself (paragraph pass, then
whole-program pass) is unchanged in all three — this is deliberately
orthogonal to what the skill already teaches, not a second way to build a
suite.

| Mode | Contract |
|---|---|
| `hands-on` | Propose first, wait for a yes before each change. Read-only commands (`analyze`, `fixtures`, `collect`, `lint`, `explain`, `doctor`) are free; anything that writes a file or executes the program waits. |
| `guided` | **Default.** Exactly today's contract: narrate every step, decide the small things, stop at the four checkpoints. |
| `hands-off` | Run the loop end to end and report once at the end. Decide what `guided` would have asked, write down each decision, park what won't go green, never stall. |

`guided` is the default precisely so that an existing project with no
`ai_mode` key behaves exactly as it did before this change.

### The floor

The load-bearing half of the design. A mode says **how often the
assistant checks in**, never **what it may destroy or quietly decide**.
Four things hold in `hands-off` exactly as in `hands-on`
(`ai_mode.ALWAYS_ASK`):

1. Never edit the `.cbl` under test.
2. Never overwrite a `.cut` containing cases the assistant didn't write
   this session (plain `generate` overwrites silently; `--fill`/`-o`
   exist for this).
3. Never turn a suspected program bug into a passing assertion.
4. Never act outside the mockymock loop on the developer's behalf (git,
   installs, deletions).

Rule 3 is the one "hands-off" is most likely to be read as licensing,
and it is exactly backwards: hands-off means *don't interrupt*, not
*decide anything*. In `hands-off` an unanswerable question becomes a
written open item in the final report — the expected value, the actual
value, and what was not done about it — and the case stays red. A
delegated run that comes back green by relaxing an assertion is worse
than one that comes back with a parked paragraph.

## Where the mode lives

In the project config file (`ai_mode` in `mockymock.toml`, or
`pyproject.toml`'s `[tool.mockymock]`), alongside `copybook_path`,
`seed`, and `test_root`:

```toml
ai_mode = "hands-off"
```

Per-repo and committed, so a team's shared answer to "how much should
this thing ask?" travels with the repo and is honored by every session
without being restated. Validated like every other key: an unknown value
is a `ConfigError` naming the valid set, not a silent fall back to the
default — same fail-closed posture as the rest of the CLI.

`MockymockConfig.ai_mode` is `str | None`, where `None` means *no key
anywhere*, distinct from a file that spells out the default explicitly.
The difference is visible in `skills mode`'s and `doctor`'s provenance
line, which is the whole point of reporting where a mode came from: a
mode set two directories up in a monorepo root is otherwise a surprise.

## The command

```bash
mockymock skills mode [--set MODE] [--json]
```

A leaf under `skills` rather than a sixteenth top-level subcommand:
`skills` is already the AI-facing surface of the CLI (`skills install`
puts the skill on disk; `skills mode` says how it behaves), and grouping
them keeps `mockymock --help` readable.

Without flags it prints the active mode, where it came from, the dial
with the active notch marked, that mode's contract in full, the floor,
and how to change it — one screen, meant to be read by an assistant at
the start of a session *and* by a developer wondering what they've
delegated. `--json` is the same content machine-readably (every mode's
contract, not just the active one, so a caller can render the dial
without keeping a copy that drifts).

`--set` persists the mode. Three cases:

- **An existing `mockymock.toml`** is edited in place, line-based, so
  comments and key order survive. `tomllib` is read-only and mockymock
  takes no TOML-*writing* dependency for the sake of one key; the file's
  schema is a flat table (every unknown key, including a `[table]`
  header, is already a `ConfigError`), so the scan is sound.
- **No config file at all** creates a `mockymock.toml` in the current
  directory.
- **A `pyproject.toml`-sourced config is a refusal**, printing the one
  line to add to `[tool.mockymock]`. Writing a `mockymock.toml` beside it
  would not merge with it — `load_config` is first-match-wins per
  directory and `mockymock.toml` wins — so the "helpful" write would
  silently shadow that project's `copybook_path`/`seed`/`test_root`.

`doctor` grows an `AI assistant mode` line, always `OK` (every mode is a
valid way to work; readiness never turns on it). It earns its place
because `doctor` is already step 0 of the skill's own workflow, so an
assistant that follows the skill learns its mode without a second
command.

### Why `--set` doesn't use `choices=MODES`

`argparse`'s `choices` would need `mockymock.cli.ai_mode` imported inside
`build_parser()`, which runs on every invocation including `--help` and
`--version` — the one import rule this CLI enforces structurally (see
`.okf/cli.md`'s Gotchas). The modes are spelled out in the flag's help
text instead and validated in `_cmd_skills_mode`;
`tests/unit/test_cli_skills.py` pins the help text against `MODES` and
pins, in a subprocess, that building the parser doesn't import the module.

## What ships in the skill

- `SKILL.md` gains a "Modes: how much to check in while you do it"
  section (the table, the floor, and the pointer to the reference), and
  its existing narration contract is relabeled as `guided`'s baseline
  with the other two modes' deltas stated where the checkpoints are
  listed. Step 0 of the workflow runs `mockymock skills mode`.
- `reference/modes.md` is the mode contract in full: each mode's
  narration/decides/asks, a worked `hands-on` exchange, the shape of a
  `hands-off` final report (including a parked-paragraph entry), the
  floor with rule 3 spelled out, and how to switch.
- `reference/paragraph-first-workflow.md` and
  `reference/scenario-generation.md` state the per-mode delta where they
  previously said "ask the developer" — notably that `hands-off` picks
  the `--scenarios` mode itself *and records the arm count and the
  reasoning*. "Don't pick silently" survives every mode; "ask first"
  doesn't.

## Alternatives considered

- **Chat-only modes (no config, no command).** Rejected: nothing
  persists, nothing is shared across a team, and "hands-off" keeps
  meaning whatever the session decides — including, eventually, rule 3.
- **A `--mode` flag on `run`/`generate`.** Wrong layer. The mode governs
  the assistant's conversation, not any single command's behavior; a flag
  would imply the CLI itself changes what it does.
- **Two modes instead of three.** `hands-on`/`hands-off` alone forces
  every existing user to pick a side, and neither side is what the skill
  does today. `guided` as the middle default is what makes this change
  behavior-preserving for anyone who ignores it.
- **A numeric autonomy level (0-3).** Unreadable in a config file, and
  it invites "level 4" — an axis with no stated floor. Named modes with a
  written contract each are auditable; a number isn't.
