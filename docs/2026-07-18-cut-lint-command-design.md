# mockymock — `.cut` Lint Command Design

Date: 2026-07-18
Status: proposed

## Motivation

The 2026-07-06 readiness audit's Finding 6 (DSL/authoring ergonomics) lists
several "silent footguns" a `.cut` author can hit. Re-checking the current
codebase before designing this turned up that two of them are no longer
silent at all:

- A second `PERFORM` in a test case already raises `CutParseError` at parse
  time.
- A duplicate `(category, key)` `MOCK` within a test case already raises
  `CutParseError` at parse time.
- An unterminated `MOCK` body already raises `CutParseError` at EOF (with
  the opening `MOCK` line's number) — not silently accepted, though the
  error can be confusing since everything after the missing `END-MOCK` was
  already swallowed into the body by the time it fires.

What's genuinely still true: a test case whose `PERFORM` target reaches an
unsupported terminator layout (`UNSUPPORTED_TERMINATOR_LAYOUT`) is only
ever detected by actually invoking `mockymock run`, which calls
`docker_toolchain.ensure_toolchain()` — and therefore requires a reachable
Docker daemon — *before* any parsing or static analysis happens at all.
The same is true of every other static refusal check (`check_whole_program`,
`check_unresolved_copybooks`, `check_linkage_layout`, `check_nested_exec`,
`check_test_case`). None of these checks actually touch Docker themselves;
they're pure static analysis over the parsed AST and the `.cut` model. The
Docker dependency is purely an artifact of `_cmd_run`'s current call order.

This is also concretely costly today: `tests/integration/test_cli.py`'s
`test_run_refuses_program_with_parse_errors` is not marked
`@requires_docker` but silently depends on Docker being reachable anyway,
because `_cmd_run` checks the toolchain before it checks the parse result.

**Goal:** add a `mockymock lint` subcommand that surfaces every existing
static refusal check, fast, with zero Docker dependency — and, as a
byproduct, make `mockymock run` itself fail on a bad `.cut`/`.cbl` without
needing Docker up first.

## Scope

**In scope:**
- A new `mockymock lint <program.cbl> --cut <file.cut> [--copybook-path DIR ...]`
  subcommand that runs the full existing static-check pipeline and reports
  every problem, with no Docker daemon required.
- Extracting that pipeline out of `_cmd_run` into a shared, reusable
  function so `run` and `lint` can never disagree about what counts as a
  refusal.
- Reordering `_cmd_run` to run static checks before `ensure_toolchain()`,
  so a bad `.cut`/`.cbl` fails fast regardless of Docker state.

**Explicitly out of scope** (considered and deferred, not forgotten):
- New heuristic checks not already covered by an existing refusal (e.g. the
  SQL schema-period tokenization quirk) — real value, but novel work with
  real false-positive risk; a separate project if pursued.
- `--junit-xml` / machine-readable output for `lint` — console-only for v1;
  a refusal-only report doesn't map cleanly onto `run`'s pass/fail JUnit
  shape anyway.
- A `.cbl`-only mode (linting before any `.cut` exists) — `generate` already
  covers that case by listing unmockable boundary points; `lint` requires
  `--cut` because the terminator-layout and per-test-case checks need a
  real `PERFORM` target to evaluate reachability against.
- The other three Finding 6 sub-projects (richer `EXPECT` operators, `CALL`
  argument capture/spies, cross-mock ordering assertions) — independent
  features, each its own future spec.

## Design

### CLI surface

```
mockymock lint <program.cbl> --cut <file.cut> [--copybook-path DIR ...]
```

Same `program` / `--cut` / `--copybook-path` arguments as `run`, minus every
flag that only matters once you're past the check phase (`--verbose`,
`--keep-sandbox`, `--coverage`, `--coverage-out`, `--junit-xml`).

Output is plain text, one line per problem in the same wording `run`
already uses for that refusal code:
```
mockymock lint: refused (UNSUPPORTED_TERMINATOR_LAYOUT): ...
mockymock lint: refused (UNRESOLVED_COPYBOOK): ...
mockymock lint: 2 problem(s) found.
```
or, clean:
```
mockymock lint: no problems found.
```
Exit 0 clean, 1 otherwise. `_cmd_lint` never imports
`mockymock.runtime.docker_toolchain` — that's a structural guarantee, not
just a documented claim.

### Shared static-check extraction

New module `mockymock/cli/checks.py`:

```python
@dataclass
class StaticCheckResult:
    problems: list[str]  # pre-formatted, unprefixed ("refused (CODE): ..." /
                          # raw indented parser-error lines), in print order
    ast: ParseResult | None = None
    surface: MockSurface | None = None
    suite: MockTestSuite | None = None
    lines: list[str] | None = None          # normalized + linkage-neutralized
    scope_map: ... | None = None
    linkage: ... | None = None

def run_static_checks(
    source_path: Path, cut_path: Path, copybook_paths: list[str] | None,
) -> StaticCheckResult: ...
```

`run_static_checks` is a faithful transcription of `_cmd_run`'s current
check sequence and short-circuit behavior — nothing about *what* is
checked or *when* it stops changes, only that it becomes callable
independently of the splice/compile/execute phase:

1. Read source; if `copybook_paths`, expand copybooks and check expansion
   warnings — stop here if any.
2. `parse_cobol`; `check_whole_program` (covers both hard parse errors and
   dropped-statement warnings) — stop here if any.
3. `check_unresolved_copybooks` — stop here if any.
4. `parse_cut` (catch `CutParseError` as a single problem line) — stop here
   if it fails.
5. `analyze` (surface), normalize lines, `check_linkage_layout` — stop here
   if any. Apply `linkage_plan`/`neutralize` to `lines` if present
   (comment-only, no line-number shift, safe to always apply before
   returning `lines`).
6. `collect_scope_map`, `annotate_nested_sites`, `check_nested_exec` — stop
   here if any.
7. `transform_data_division_exec` in check-only mode (discard transformed
   lines, keep only refusal reasons) — stop here if any.
8. `check_test_case` per test case, then `check_terminator_layout` —
   **accumulate** problems across all test cases (matching today's
   behavior) rather than stopping at the first.

If step 8 produced no problems, `problems` is empty and every artifact
field is populated with what `_cmd_run` needs to proceed straight to
splicing (`boundaries`/`registry`/`terminator_plans`/`splice_program`/
`build_driver`) without recomputing anything already done here.

### `_cmd_run` reorder

Today, `_cmd_run` calls `ensure_toolchain()` before any parsing or refusal
checks — so a typo'd `.cut` or a program with parse errors pays the Docker
cost first, and a Docker-unreachable environment surfaces a misleading
"Docker not available" message instead of the real problem. This mirrors a
principle the codebase already applies to file existence
(`_check_input_files`'s docstring: "a typo'd path must not pay that cost").

`_cmd_run` will call `run_static_checks(...)` first, print and return 1 on
any problems, and only call `ensure_toolchain()` once the check phase is
clean and it's actually about to splice and compile:

- Docker available (the tested, common case): identical behavior/output to
  today.
- Docker unavailable, real `.cut`/`.cbl` problem: now shows the actual
  problem instead of a misleading Docker error — strictly better.
- Docker unavailable, clean `.cut`/`.cbl`: same outcome as today (Docker
  error), just reached slightly later.

### `_cmd_lint`

```python
def _cmd_lint(args: argparse.Namespace) -> int:
    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock lint", source_path, cut_path):
        return 1
    result = run_static_checks(source_path, cut_path, args.copybook_path)
    for problem in result.problems:
        print(f"mockymock lint: {problem}")
    if result.problems:
        print(f"mockymock lint: {len(result.problems)} problem(s) found.")
        return 1
    print("mockymock lint: no problems found.")
    return 0
```

## Testing

- **Unit** (`tests/unit/test_checks.py`, new): exercise `run_static_checks`
  directly against each short-circuit stage — expansion warning, parse
  error, whole-program warning, unresolved copybook, `.cut` parse error,
  linkage-layout refusal, nested-EXEC refusal, per-test-case refusal,
  terminator-layout refusal, and the all-clean success path (assert
  returned artifacts are populated). Reuse fixtures already in
  `tests/unit/test_refusal.py`/`test_refusal_v2.py` where they cover the
  same codes.
- **CLI** (`tests/unit/test_cli.py`, existing non-Docker file): add `lint`
  tests — a clean example → exit 0, `"no problems found"`; a broken one
  (e.g. unresolved copybook or terminator-layout) → exit 1 with the
  expected problem text. Living in the non-Docker test file is itself part
  of the proof that `lint` needs no daemon.
- **Regression backstop**: the full existing unit + integration suite
  (`tests/integration/test_cli.py`'s `run` tests, `test_terminator_support.py`,
  every worked `examples/` integration test) must stay green unchanged —
  that's what proves the `_cmd_run` refactor didn't change its
  externally-visible behavior.

## Docs to update after implementation

- `.okf/cli.md` (and `.okf/dsl.md`'s "See Also" line) — document `lint`
  alongside `generate`/`run`.
- `README.md` — short "Linting without Docker" section.
- `docs/2026-07-06-real-world-readiness-audit.md` Finding 6 — mark the
  `.cut`-linter row closed, and correct the stale "duplicate `PERFORM`
  silently wins" / "unterminated `MOCK` silently swallows" claims (both
  already fail closed today, as discovered while scoping this design).

## Alternatives considered

- **Independent `_cmd_lint` implementation, no shared extraction.** Zero
  risk to the existing `run` path since nothing there changes, but
  duplicates the ~150-line check sequence — a future change to check
  ordering in one place could silently drift from the other. Rejected:
  this is exactly the "two copies of one rule" risk the codebase already
  guards against elsewhere (e.g. the parser/driver expectation-validation
  sync comment in `.okf/dsl.md`).
- **`mockymock run --dry-run` instead of a new subcommand.** Shares code
  trivially (same function, early return) but less discoverable for
  CI/pre-commit/editor use, and raises awkward questions about what
  `--coverage`/`--junit-xml` should mean under dry-run. Rejected in favor
  of a dedicated verb.
