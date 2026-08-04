# Mainframe (z/OS) Export Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mockymock export` (CLI, Docker-free) and a VS Code palette command that write mockymock's instrumented, mock-only COBOL build to a file adjusted for a real fixed-format (z/OS) COBOL compile instead of GnuCOBOL-only.

**Architecture:** Reuse `run`'s existing parse → static-checks → splice → driver-insert pipeline (stopping before any Docker step), then apply three new export-only adjustments — preserved `PROCESS`/`CBL` directives, restored fixed-format columns (7-space padding + `DISPLAY`-statement wrapping), and a provenance/disclaimer header — before writing to a file. A VS Code command shells out to the new CLI subcommand.

**Tech Stack:** Python 3 (mockymock CLI, `cobolparser`), TypeScript (VS Code extension), pytest (unit + Docker-gated integration), mocha (extension unit tests).

## Global Constraints

- No Docker/GnuCOBOL dependency anywhere in the new CLI command's success path — matches `generate`/`lint`/`collect`'s existing Docker-free pattern (see `.okf/cli.md`).
- `run`/`lint`/`debug`/`mutate`'s existing behavior must not change — every shared-code modification (`run_static_checks`, `_write_report_file`) adds an optional parameter with a default that preserves current behavior.
- Every new function that touches column/line text must be validated against the empirical findings in `docs/2026-08-03-mainframe-export-command-design.md` (Adjustments 1–3) — those findings came from real spikes against the installed `cobolparser`/`mockymock` and a real `mockymock-cobc` Docker container, not from reasoning about docstrings alone.
- No JCL generation, no `--target` flag, no `cobc -std=ibm` smoke-compile — all explicitly out of scope per the design doc.

## File Structure

- **Create** `mockymock/cli/mainframe_export.py` — the three export-only text transforms: `restore_fixed_format_columns`, `wrap_long_display_lines`, `build_provenance_header` / `insert_provenance_header`. Nothing here is imported by `run`/`lint`/`debug`/`mutate`.
- **Modify** `mockymock/cli/checks.py` — `run_static_checks` gains `preserve_compiler_directives: bool = False`.
- **Modify** `mockymock/cli/main.py` — new `_cmd_export`, `export_parser` wiring in `build_parser()`, and `_write_report_file` gains a `command: str` parameter (all 4 existing call sites in `_cmd_run` updated to pass `"run"`).
- **Create** `tests/unit/test_mainframe_export.py` — unit tests for the three new functions.
- **Modify** `tests/unit/test_checks.py` — one new test for `preserve_compiler_directives=True`.
- **Create** `tests/unit/test_cli_export.py` — CLI-level tests for `_cmd_export` (mirrors `tests/unit/test_cli.py`'s style).
- **Create** `tests/integration/test_export_display_wrap.py` — Docker-gated regression test pinning the byte-identical-stdout finding.
- **Modify** `.okf/cli.md`, `.okf/index.md`, `.okf/log.md`, `README.md` — document the new subcommand per this workspace's OKF-maintenance convention.
- **Create** `mocky-mock-vscode-extension/src/export/exportMainframe.ts` — the VS Code command, split into testable pure/async logic (`buildExportArgs`, `runExport`) and a thin VS Code-API registration function (`activateExportMainframeCommand`), mirroring `src/testing/mockymockRunner.ts`'s split.
- **Modify** `mocky-mock-vscode-extension/src/discovery/cutDiscovery.ts` — add `resolveCutPath` (the `.cbl` → `.cut` inverse of the existing `resolveCblPath`).
- **Modify** `mocky-mock-vscode-extension/src/extension.ts` — register the new command.
- **Modify** `mocky-mock-vscode-extension/package.json` — add the `mockymock.exportMainframe` command contribution.
- **Create** `mocky-mock-vscode-extension/src/export/exportMainframe.test.ts` — mirrors `mockymockRunner.test.ts`'s fake-`CommandRunner` style.

---

### Task 1: `restore_fixed_format_columns` + provenance header

**Files:**
- Create: `mockymock/cli/mainframe_export.py`
- Test: `tests/unit/test_mainframe_export.py`

**Interfaces:**
- Produces: `restore_fixed_format_columns(lines: list[str]) -> list[str]`, `build_provenance_header(program_path: str, cut_path: str) -> list[str]`, `insert_provenance_header(lines: list[str], header: list[str]) -> list[str]`, module constant `COLUMN_LIMIT = 72`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_mainframe_export.py`:

```python
"""Unit tests for mockymock.cli.mainframe_export -- the export-only text
transforms that make the instrumented source z/OS-compilable. See
docs/2026-08-03-mainframe-export-command-design.md for the empirical basis
(spiked against a real cobolparser install and a real GnuCOBOL container
before this code was written)."""
from mockymock.cli.mainframe_export import (
    build_provenance_header,
    insert_provenance_header,
    restore_fixed_format_columns,
)


def test_restore_fixed_format_columns_prepends_seven_spaces():
    lines = ["IDENTIFICATION DIVISION.", "", "PROGRAM-ID. X."]
    result = restore_fixed_format_columns(lines)
    assert result == [
        "       IDENTIFICATION DIVISION.",
        "       ",
        "       PROGRAM-ID. X.",
    ]


def test_restore_fixed_format_columns_preserves_line_count():
    lines = ["A"] * 50
    assert len(restore_fixed_format_columns(lines)) == 50


def test_provenance_header_lines_all_fit_within_72_columns():
    header = build_provenance_header("PROG.cbl", "PROG.cut")
    assert all(len(line) <= 72 for line in header)


def test_provenance_header_names_source_files_by_basename_only():
    header = build_provenance_header(
        "C:/very/deeply/nested/workspace/path/PROG.cbl",
        "C:/very/deeply/nested/workspace/path/PROG.cut",
    )
    joined = "\n".join(header)
    assert "PROG.cbl" in joined
    assert "PROG.cut" in joined
    assert "very/deeply/nested" not in joined


def test_provenance_header_mentions_mock_only_and_finding_1():
    header = "\n".join(build_provenance_header("P.cbl", "P.cut"))
    assert "MOCK-ONLY" in header
    assert "real-world-readiness-audit" in header


def test_insert_provenance_header_lands_before_identification_division():
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. X.",
    ]
    header = ["      *> header line 1", "      *> header line 2", ""]
    result = insert_provenance_header(lines, header)
    assert result == [
        "      *> header line 1",
        "      *> header line 2",
        "",
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. X.",
    ]


def test_insert_provenance_header_lands_after_a_preserved_directive():
    """PROCESS/CBL directives must precede IDENTIFICATION DIVISION -- the
    header must not be inserted between a preserved directive and it."""
    lines = [
        "       CBL APOST",
        "       IDENTIFICATION DIVISION.",
    ]
    header = ["      *> header", ""]
    result = insert_provenance_header(lines, header)
    assert result == [
        "       CBL APOST",
        "      *> header",
        "",
        "       IDENTIFICATION DIVISION.",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_mainframe_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mockymock.cli.mainframe_export'`

- [ ] **Step 3: Write the implementation**

Create `mockymock/cli/mainframe_export.py`:

```python
"""Export-only adjustments that make the instrumented source compilable
under a real fixed-format (columns 1-72) COBOL compiler instead of only
GnuCOBOL's free-form (`cobc -free`) mode. Nothing here is imported by
`run`/`lint`/`debug`/`mutate` -- see
docs/2026-08-03-mainframe-export-command-design.md for the empirical
basis (spiked against a real cobolparser install and a real
`mockymock-cobc` container before this module was written).
"""

from __future__ import annotations

from pathlib import Path

COLUMN_LIMIT = 72

# Columns 1-6 (sequence area) + column 7 (indicator), both blank: what
# normalize_fixed_format's "extract program text cols 8-72" strips away.
_SEQUENCE_AREA = "       "


def restore_fixed_format_columns(lines: list[str]) -> list[str]:
    """Undo normalize_fixed_format's column-8-72 extraction by prepending
    the 7 blank columns it stripped, so every original-source-derived
    line's content lands at its true column again -- matching the
    convention splicer-generated lines (driver.py, injector.py,
    _insert_driver) already assume (index 0 = column 1). Call this on
    `run_static_checks`'s returned `lines`, BEFORE collect_boundaries/
    splice_program -- both are line-granular, never column-position-
    sensitive (verified during design), so this uniform prefix is
    transparent to them."""
    return [_SEQUENCE_AREA + line for line in lines]


def build_provenance_header(program_path: str, cut_path: str) -> list[str]:
    """A comment block (real column-7 `*>` inline-comment markers, like
    splicer/sqlca.py's own generated comments) stating this build is
    mock-only and naming the GnuCOBOL-vs-IBM-COBOL gaps a clean compile
    here does not rule out. Source paths are basenames only -- a full
    path could exceed 72 columns on its own, and the exact path isn't
    load-bearing provenance (the invocation that produced this file
    already is)."""
    lines = [
        "      *> Generated by `mockymock export` -- do not edit by hand.",
        f"      *> Source program: {Path(program_path).name}",
        f"      *> Source test file: {Path(cut_path).name}",
        "      *>",
        "      *> MOCK-ONLY BUILD: every CALL / file I-O / EXEC SQL,CICS,DLI /",
        "      *> ACCEPT boundary below is a test double or a fail-loud stub --",
        "      *> no real I/O executes anywhere in this program, here or under",
        "      *> GnuCOBOL. A clean compile+run validates the COMPUTATIONAL core",
        "      *> only: control flow, MOVE/COMPUTE logic, CALL/mock invocation",
        "      *> counts and ordering.",
        "      *>",
        "      *> A clean compile does NOT prove equivalence with GnuCOBOL on:",
        "      *>   EBCDIC vs ASCII collation (alphanumeric / 88-level compares)",
        "      *>   COMP-3 / zoned-decimal sign and truncation edge behavior",
        "      *>   Intermediate arithmetic (COMPUTE / rounding) precision",
        "      *>   Numeric-edited PICTURE clauses and IBM intrinsic functions",
        "      *> See docs/2026-07-06-real-world-readiness-audit.md, Finding 1.",
        "",
    ]
    # Defensive: every line above is verified under 72 chars by
    # test_provenance_header_lines_all_fit_within_72_columns, but an
    # unusually long basename could still push a path line over.
    return [line if len(line) <= COLUMN_LIMIT else line[:69] + "..." for line in lines]


def insert_provenance_header(lines: list[str], header: list[str]) -> list[str]:
    """Insert `header` immediately before the IDENTIFICATION DIVISION
    line, so any preserved PROCESS/CBL directive (which must precede it)
    stays first -- matching _insert_driver's own "find the header line,
    splice relative to it" convention."""
    for index, line in enumerate(lines):
        if line.strip().upper().startswith("IDENTIFICATION DIVISION"):
            return lines[:index] + header + lines[index:]
    return header + lines  # defensive: refusal gates guarantee this exists
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_mainframe_export.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add mockymock/cli/mainframe_export.py tests/unit/test_mainframe_export.py
git commit -m "feat(cli): add column-restoration and provenance-header helpers for mainframe export"
```

---

### Task 2: `wrap_long_display_lines`

**Files:**
- Modify: `mockymock/cli/mainframe_export.py`
- Test: `tests/unit/test_mainframe_export.py`

**Interfaces:**
- Consumes: `COLUMN_LIMIT` (Task 1).
- Produces: `wrap_long_display_lines(lines: list[str], max_col: int = COLUMN_LIMIT) -> tuple[list[str], list[str]]` — returns `(new_lines, overflow_problems)`; `overflow_problems` is empty on full success.

This is the highest-risk piece of the feature, and its final shape is the
product of finding and fixing two real bugs during design, not a
first-draft algorithm. In order:

1. Round-trip correctness (literal + trailing text reconstructs exactly)
   was checked against 5 real over-72 lines pulled from
   `examples/custprog/`'s actual instrumented output plus 2 synthetic edge
   cases (trailing period, embedded escaped quote) — all passed.
2. The wrap mechanism itself (`DISPLAY "frag" WITH NO ADVANCING` chains)
   was compiled and run through the real `mockymock-cobc` container,
   confirming byte-identical stdout against the unwrapped original.
3. A 5000-case randomized stress test (varying indentation, literal
   length, trailing expression, embedded quotes) then found **104
   failures**: a single-character-index boundary adjustment (nudging a
   split point by one to avoid bisecting a `""` escape pair) wasn't
   robust when multiple escape pairs clustered near a split point,
   producing either an unparseable fragment or a line still over 72
   columns with no problem reported.
4. The fix was a redesign, not a patch: chunk by **atomic units**
   (`_atomic_units`/`_chunk_units` below) where a `""` pair is one
   indivisible 2-character unit, so a chunk boundary can never fall
   inside one regardless of how many cluster together. A follow-up
   20,000-case adversarial stress test (heavy escaped-quote density,
   indentation to 50 columns) against the redesign found **zero**
   round-trip or malformed-fragment failures.
5. That same adversarial run surfaced one narrow residual: sufficiently
   deep indentation (~43+ columns, clustering escaped quotes right at the
   split point) can still force one fragment 1-2 characters over `max_col`
   — the only way a 2-character escape-pair unit can avoid being split is
   to let it overshoot a 1-character budget. `wrap_long_display_lines`
   closes this with a final length check on every produced fragment,
   refusing (rather than shipping the oversized one) if it ever fires —
   which the same 20,000-case run confirms happens only in that
   deep-indentation scenario, never on any shape `driver.py`/`injector.py`
   actually generate.

Task 5's `_cmd_export` integration and Task 6's Docker-gated integration
test are what turn steps 1-2's manual verification into a permanent
regression guard; the test list below (Step 1) includes regression tests
for the bug found in step 3 and the residual from step 5, not just the
original real-line cases.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_mainframe_export.py`:

```python
from mockymock.cli.mainframe_export import wrap_long_display_lines

# The five lines below are the ACTUAL over-72-column lines produced by
# splicing examples/custprog/CUSTPROG.cbl + CUSTPROG.cut (captured during
# design, before this module existed) -- driver.py/injector.py DISPLAY
# calls, not user-authored text.
REAL_OVERFLOW_LINES = [
    '               DISPLAY "__MOCKYMOCK__ CASE 001 FAIL: VERIFY SQL FETCH CUST_CURSOR WAS CALLED 3 TIMES, got " FUNCTION TRIM(UT-TALLY-EDITED)',
    '               DISPLAY "__MOCKYMOCK__ CASE 001 FAIL: expected WS-ROW-COUNT = 2, got " WS-ROW-COUNT',
    '           DISPLAY "__MOCKYMOCK__ CASE 001 START: fetches two customers then exhausts"',
    '                   DISPLAY "__MOCKYMOCK__ ERROR: SQL boundary (line 18) reached "',
    '           DISPLAY "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=" UT-FAIL-COUNT',
]


def test_short_lines_pass_through_unchanged():
    lines = ['           DISPLAY "short"', "some other line"]
    result, problems = wrap_long_display_lines(lines)
    assert result == lines
    assert problems == []


def test_real_overflow_lines_all_wrap_under_72_with_no_problems():
    result, problems = wrap_long_display_lines(REAL_OVERFLOW_LINES)
    assert problems == []
    assert all(len(line) <= 72 for line in result)
    # Each original line's overflow produced at least 2 output lines.
    assert len(result) > len(REAL_OVERFLOW_LINES)


def test_wrap_preserves_leading_indentation_on_every_fragment():
    line = (
        '                   DISPLAY "__MOCKYMOCK__ ERROR: SQL boundary '
        '(line 18) reached "'
    )
    result, problems = wrap_long_display_lines([line])
    assert problems == []
    assert all(l.startswith("                   DISPLAY") for l in result)


def test_wrap_uses_with_no_advancing_on_every_fragment_but_the_last():
    result, problems = wrap_long_display_lines([REAL_OVERFLOW_LINES[0]])
    assert problems == []
    for fragment in result[:-1]:
        assert fragment.endswith("WITH NO ADVANCING")
    assert not result[-1].endswith("WITH NO ADVANCING")


def test_wrap_reconstructs_the_exact_original_literal_and_trailing_expr():
    """Concatenating every fragment's literal text (in order) plus the
    final fragment's trailing expression/period must exactly reproduce
    what the single unwrapped DISPLAY would have printed."""
    import re

    display_re = re.compile(r"^(?P<indent>\s*)DISPLAY\s+(?P<rest>.+)$", re.IGNORECASE)

    def parse_args(rest):
        pos, length, chunks, found = 0, len(rest), [], False
        while pos < length:
            while pos < length and rest[pos] == " ":
                pos += 1
            if pos >= length or rest[pos] != '"':
                break
            found = True
            pos += 1
            piece = []
            while True:
                if rest[pos] == '"':
                    if pos + 1 < length and rest[pos + 1] == '"':
                        piece.append('"')
                        pos += 2
                        continue
                    pos += 1
                    break
                piece.append(rest[pos])
                pos += 1
            chunks.append("".join(piece))
        if not found:
            return None
        return "".join(chunks), rest[pos:].strip()

    for original in REAL_OVERFLOW_LINES:
        wrapped, problems = wrap_long_display_lines([original])
        assert problems == []

        literal_parts = []
        trailing_expr = ""
        for i, fragment in enumerate(wrapped):
            rest = display_re.match(fragment).group("rest")
            is_last = i == len(wrapped) - 1
            if not is_last:
                assert rest.endswith(" WITH NO ADVANCING")
                rest = rest[: -len(" WITH NO ADVANCING")]
            lit, trailing = parse_args(rest)
            literal_parts.append(lit)
            if is_last:
                trailing_expr = trailing

        orig_rest = display_re.match(original).group("rest")
        orig_literal, orig_trailing = parse_args(orig_rest)
        assert "".join(literal_parts) == orig_literal
        assert trailing_expr == orig_trailing


def test_wrap_handles_a_trailing_period():
    line = (
        '           DISPLAY "__MOCKYMOCK__ CASE 001 END: this is a '
        'deliberately very long case-end marker for testing purposes here".'
    )
    result, problems = wrap_long_display_lines([line])
    assert problems == []
    assert all(len(l) <= 72 for l in result)
    assert result[-1].endswith(".")
    assert not any(l.endswith(".") for l in result[:-1])


def test_wrap_never_splits_an_escaped_doubled_quote():
    line = (
        '           DISPLAY "__MOCKYMOCK__ CASE 001 START: a case name with '
        'an embedded ""quoted phrase"" right in the middle of it"'
    )
    result, problems = wrap_long_display_lines([line])
    assert problems == []
    for fragment in result:
        # An odd number of quote characters means a doubled pair was
        # bisected -- each fragment's literal must be independently
        # well-formed (an even count of quote chars inside the outer
        # delimiters).
        inner = fragment[fragment.index('"') + 1 : fragment.rindex('"')]
        assert inner.count('"') % 2 == 0


def test_unwrappable_line_is_reported_not_silently_kept_long():
    line = "           MOVE " + "X" * 80 + " TO SOME-FIELD"
    result, problems = wrap_long_display_lines([line])
    assert len(problems) == 1
    assert "line 1" in problems[0]
    assert result == [line]


def test_atomic_units_keeps_doubled_quote_pairs_together():
    from mockymock.cli.mainframe_export import _atomic_units

    units = _atomic_units('AB""CD""""EF')
    assert units == ["A", "B", '""', "C", "D", '""', '""', "E", "F"]
    assert "".join(units) == 'AB""CD""""EF'


def test_chunk_units_never_splits_a_unit_and_clamps_non_positive_budget():
    from mockymock.cli.mainframe_export import _atomic_units, _chunk_units

    units = _atomic_units('AB""CD')
    for budget in (-5, 0, 1, 2, 3, 10):
        chunks = _chunk_units(units, budget)
        assert "".join(chunks) == 'AB""CD'
        for chunk in chunks:
            assert chunk.count('"') % 2 == 0


def test_wrap_refuses_cleanly_when_clustered_escapes_leave_no_valid_cut():
    """White-box regression guard for the deep-indentation edge case
    found during design (a 20,000-case randomized stress test): when the
    wrap budget is squeezed down to ~1 character by deep indentation and
    a run of escaped quotes clusters right at the only available split
    point, no chunking can produce a fragment within max_col without
    bisecting a doubled-quote pair. This must REFUSE (fail closed, named
    COLUMN_OVERFLOW by the caller), not silently ship an over-length
    fragment -- not reachable by any current mockymock-generated shape
    (needs ~43 columns of indentation), but the function's contract
    (every returned line fits, or the line is in problems) must hold for
    any input."""
    indent = " " * 43
    literal = '""' * 18  # a long run of escaped-quote pairs
    line = f'{indent}DISPLAY "{literal}"'
    assert len(line) > 72

    result, problems = wrap_long_display_lines([line])
    assert len(problems) == 1
    assert "could not wrap under column 72" in problems[0]
    assert result == [line]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_mainframe_export.py -k wrap -v`
Expected: FAIL with `ImportError: cannot import name 'wrap_long_display_lines'`

- [ ] **Step 3: Write the implementation**

Add to `mockymock/cli/mainframe_export.py` (after the imports, before `restore_fixed_format_columns`, add `import re`; the new functions go at the end of the file):

```python
_DISPLAY_RE = re.compile(r"^(?P<indent>\s*)DISPLAY\s+(?P<rest>.+)$", re.IGNORECASE)


def _parse_display_args(rest: str) -> tuple[str, str] | None:
    """Split a DISPLAY statement's argument text (period already
    stripped) into (literal_text, trailing_expr): literal_text is the
    concatenated, UNESCAPED text of every leading adjacent quoted-literal
    operand; trailing_expr is whatever non-literal text follows (may be
    ''). Returns None if the argument text doesn't start with a literal
    -- not a shape this wraps."""
    pos = 0
    length = len(rest)
    literal_chunks: list[str] = []
    found_any_literal = False
    while pos < length:
        while pos < length and rest[pos] == " ":
            pos += 1
        if pos >= length or rest[pos] != '"':
            break
        found_any_literal = True
        pos += 1  # past opening quote
        piece: list[str] = []
        while True:
            if pos >= length:
                return None  # unterminated literal -- not our shape
            if rest[pos] == '"':
                if pos + 1 < length and rest[pos + 1] == '"':
                    piece.append('"')
                    pos += 2
                    continue
                pos += 1  # past closing quote
                break
            piece.append(rest[pos])
            pos += 1
        literal_chunks.append("".join(piece))
    if not found_any_literal:
        return None
    return "".join(literal_chunks), rest[pos:].strip()


def _atomic_units(escaped_text: str) -> list[str]:
    """Split already-escaped literal text into atomic units: a
    doubled-quote escape pair ('""') is one 2-character unit that must
    never be split across a chunk boundary; every other character is its
    own 1-character unit. Grouping by whole units (in _chunk_units below)
    guarantees no chunk boundary ever bisects a pair, regardless of how
    many escaped quotes cluster together -- an earlier version that
    nudged a single character-index split point by one instead failed a
    5000-case randomized stress test (104 failures, all from multiple
    adjacent escape pairs) during design. This unit-based approach fixed
    all of those; the one residual gap it cannot fully close on its own
    (a single 2-char unit that alone exceeds a 1-char budget, only
    reachable with ~42+ columns of indentation) is caught by
    wrap_long_display_lines's own final length check on each produced
    fragment, not by this function -- see _chunk_units and the caller's
    safety-net comment."""
    units: list[str] = []
    i = 0
    n = len(escaped_text)
    while i < n:
        if escaped_text[i] == '"' and i + 1 < n and escaped_text[i + 1] == '"':
            units.append(escaped_text[i : i + 2])
            i += 2
        else:
            units.append(escaped_text[i])
            i += 1
    return units


def _chunk_units(units: list[str], budget: int) -> list[str]:
    """Greedily group atomic units (never splitting one) into chunks of
    at most `budget` characters each. A single oversized unit (only
    possible for a 2-char escape pair with budget < 2, which needs
    indentation deep enough to push the wrap budget that low -- ~42
    columns, not something any current mockymock output produces) is
    still emitted as its own chunk rather than looping forever; the
    caller (wrap_long_display_lines) checks every fragment's final
    length afterward and refuses instead of accepting an oversized one,
    so this never silently ships a too-long line."""
    budget = max(budget, 1)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        if current and current_len + len(unit) > budget:
            chunks.append("".join(current))
            current = []
            current_len = 0
        current.append(unit)
        current_len += len(unit)
    if current:
        chunks.append("".join(current))
    return chunks


def wrap_long_display_lines(
    lines: list[str], max_col: int = COLUMN_LIMIT
) -> tuple[list[str], list[str]]:
    """Split every over-`max_col` DISPLAY statement matching mockymock's
    own generated shape -- `DISPLAY "<literal>"[ <trailing non-literal
    expression>][.]`, the only shape driver.py/injector.py ever produce
    -- into `DISPLAY "<chunk>" WITH NO ADVANCING` fragments (re-escaping
    doubled quotes per chunk) plus a final plain DISPLAY carrying the
    trailing expression and any original trailing period. Verified
    empirically to produce byte-identical stdout to the unwrapped
    original (docs/2026-08-03-mainframe-export-command-design.md,
    Adjustment 2b).

    A line that still can't be brought under `max_col` (not a DISPLAY,
    not this shape, or a trailing expression alone too long to fit) is
    reported in the returned problems list instead of silently kept
    long -- the honest fail-closed backstop, expected to fire
    approximately never given the shapes actually generated today."""
    new_lines: list[str] = []
    problems: list[str] = []
    for line_no, line in enumerate(lines, start=1):
        if len(line) <= max_col:
            new_lines.append(line)
            continue
        match = _DISPLAY_RE.match(line)
        if match is None:
            problems.append(
                f"line {line_no} exceeds column {max_col} and is not a "
                f"wrappable DISPLAY statement: {line!r}"
            )
            new_lines.append(line)
            continue
        indent = match.group("indent")
        rest = match.group("rest")
        trailing_period = rest.endswith(".")
        if trailing_period:
            rest = rest[:-1]
        parsed = _parse_display_args(rest)
        if parsed is None:
            problems.append(
                f"line {line_no} exceeds column {max_col} and its DISPLAY "
                f"arguments aren't a recognized literal[+expr] shape: {line!r}"
            )
            new_lines.append(line)
            continue
        literal_text, trailing_expr = parsed
        escaped = literal_text.replace('"', '""')

        final_suffix = ""
        if trailing_expr:
            final_suffix += " " + trailing_expr
        if trailing_period:
            final_suffix += "."
        final_overhead = len(indent) + len('DISPLAY "') + len('"') + len(final_suffix)
        final_budget = max_col - final_overhead
        # final_budget < len(escaped) always holds at this point: `line`
        # is already known to exceed max_col, and final_overhead +
        # len(escaped) is exactly what an unwrapped DISPLAY of this shape
        # measures -- so there is no "it already fits, skip wrapping"
        # case to special-case here (confirmed by a 20,000-case randomized
        # search during design: 0 hits).

        if final_budget <= 0:
            problems.append(
                f"line {line_no}: trailing expression {trailing_expr!r} "
                f"alone leaves no room on the final fragment: {line!r}"
            )
            new_lines.append(line)
            continue

        mid_overhead = len(indent) + len('DISPLAY "') + len('" WITH NO ADVANCING')
        mid_budget = max_col - mid_overhead
        if mid_budget <= 0:
            problems.append(
                f"line {line_no}: indentation alone leaves no room to "
                f"wrap: {line!r}"
            )
            new_lines.append(line)
            continue

        # Peel whole units off the END, greedily, until adding one more
        # would exceed final_budget -- those become the final fragment's
        # literal; everything before them gets chunked into WITH NO
        # ADVANCING fragments. Unit-based (never bisects a doubled-quote
        # escape pair) regardless of how many cluster near the split.
        units = _atomic_units(escaped)
        tail_units: list[str] = []
        tail_len = 0
        for unit in reversed(units):
            if tail_len + len(unit) > final_budget:
                break
            tail_units.insert(0, unit)
            tail_len += len(unit)
        head_units = units[: len(units) - len(tail_units)]
        tail = "".join(tail_units)

        fragments = [
            f'{indent}DISPLAY "{chunk}" WITH NO ADVANCING'
            for chunk in _chunk_units(head_units, mid_budget)
        ]
        fragments.append(f'{indent}DISPLAY "{tail}"{final_suffix}')
        # Final safety net: _chunk_units's oversized-unit fallback (see
        # its docstring) can, in the same deep-indentation edge case,
        # produce one fragment a character or two over max_col. Refusing
        # here instead of shipping it is what "fail closed, never
        # silently wrong" means for this function -- verified against
        # 20,000 adversarial cases (heavy escaped-quote density,
        # indentation to 50 columns) during design: this path fires only
        # there, never on any real mockymock-generated shape.
        oversized = [f for f in fragments if len(f) > max_col]
        if oversized:
            problems.append(
                f"line {line_no}: could not wrap under column {max_col} "
                f"-- clustered escaped quotes near the split point left "
                f"no valid cut: {line!r}"
            )
            new_lines.append(line)
            continue
        new_lines.extend(fragments)
    return new_lines, problems
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_mainframe_export.py -v`
Expected: PASS (all tests in the file, including Task 1's)

- [ ] **Step 5: Commit**

```bash
git add mockymock/cli/mainframe_export.py tests/unit/test_mainframe_export.py
git commit -m "feat(cli): wrap over-72-column generated DISPLAY statements for mainframe export"
```

---

### Task 3: `preserve_compiler_directives` on `run_static_checks`

**Files:**
- Modify: `mockymock/cli/checks.py:88-99,176-186`
- Test: `tests/unit/test_checks.py`

**Interfaces:**
- Produces: `run_static_checks(..., preserve_compiler_directives: bool = False)` — default unchanged behavior for existing callers (`run`, `lint`, `debug`).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_checks.py`:

```python
def test_preserve_compiler_directives_keeps_them_in_lines(tmp_path):
    """export needs the real PROCESS/CBL directives kept intact (GnuCOBOL
    can't compile them, but a real IBM compiler expects them) -- opt-in
    via preserve_compiler_directives, default False leaves run/lint
    unaffected (see test_precompiler_directives_stripped_before_lines_
    reach_the_compiler above)."""
    cbl = tmp_path / "PRECHK.cbl"
    cbl.write_text("""\
       PROCESS APOST,TRUNC(OPT)
       CBL ARITH(EXTEND)
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRECHK.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           DISPLAY "HELLO".
""")
    cut = tmp_path / "PRECHK.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PROCESS\n')

    stripped = run_static_checks(cbl, cut, None)
    assert stripped.ok
    assert "PROCESS" not in stripped.lines[0]

    preserved = run_static_checks(cbl, cut, None, preserve_compiler_directives=True)
    assert preserved.ok
    assert preserved.lines[0] == "PROCESS APOST,TRUNC(OPT)"
    assert preserved.lines[1] == "CBL ARITH(EXTEND)"
    # Line count (and every later AST-derived line number) must match
    # the stripped variant exactly -- same invariant, opposite content.
    assert len(preserved.lines) == len(stripped.lines)
    assert preserved.lines[2] == stripped.lines[2] == "IDENTIFICATION DIVISION."
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_checks.py -k preserve_compiler_directives -v`
Expected: FAIL with `TypeError: run_static_checks() got an unexpected keyword argument 'preserve_compiler_directives'`

- [ ] **Step 3: Modify the implementation**

In `mockymock/cli/checks.py`, change the signature at line 88-94:

```python
def run_static_checks(
    source_path: Path,
    cut_path: Path,
    copybook_paths: list[str] | None,
    case_names: list[str] | None = None,
    tag_names: list[str] | None = None,
    preserve_compiler_directives: bool = False,
) -> StaticCheckResult:
```

And change lines 176-186 (the comment stays accurate for the default case; add a note for the new branch):

```python
    # PROCESS/CBL precompiler directives (IBM mainframe compiler-directing
    # statements preceding IDENTIFICATION DIVISION) parse fine as far as
    # cobolparser is concerned -- CobolParser.parse() blanks them out for its
    # own AST -- but `lines` here is what the splicer edits and what
    # eventually gets written as the instrumented source for GnuCOBOL to
    # compile. Left in place, they survive into that file verbatim and cobc
    # can reject options/syntax it doesn't recognize. Strip them the same way
    # before normalizing so they never reach the toolchain -- unless the
    # caller (mockymock export) wants them preserved for a real IBM compile
    # instead, which needs them exactly where GnuCOBOL can't tolerate them.
    if preserve_compiler_directives:
        lines = normalize_fixed_format(raw_source.splitlines()).splitlines()
    else:
        lines = normalize_fixed_format(
            strip_compiler_directives(raw_source).splitlines()
        ).splitlines()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_checks.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add mockymock/cli/checks.py tests/unit/test_checks.py
git commit -m "feat(cli): add preserve_compiler_directives option to run_static_checks"
```

---

### Task 4: `_cmd_export` CLI wiring

**Files:**
- Modify: `mockymock/cli/main.py` (add `_cmd_export`; add `export_parser` in `build_parser()`; generalize `_write_report_file`; update its 4 existing call sites in `_cmd_run`)
- Test: Create `tests/unit/test_cli_export.py`

**Interfaces:**
- Consumes: `run_static_checks(..., preserve_compiler_directives=True)` (Task 3); `restore_fixed_format_columns`, `wrap_long_display_lines`, `build_provenance_header`, `insert_provenance_header` (Tasks 1-2); existing `collect_boundaries`, `TallyRegistry`, `find_terminator_plans`, `find_flow_mock_plans`, `splice_program`, `transform_data_division_exec`, `reset_move_lines`, `build_driver`, `_insert_driver` (all already used identically by `_cmd_run`).
- Produces: `mockymock export <program> --cut PATH [-o/--output PATH] [--copybook-path DIR ...] [--case NAME ...] [--tag TAG ...]`, exit 0 on success (writes `--output`, default `<program-stem>.mainframe.cbl`), exit 1 on any refusal (nothing written).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cli_export.py`:

```python
"""CLI behavior tests for `mockymock export` (Docker-free, mirrors
tests/unit/test_cli.py's style)."""
from pathlib import Path

from mockymock.cli.main import main

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_export_missing_inputs_fail_cleanly(tmp_path, capsys):
    exit_code = main(
        ["export", str(tmp_path / "NOPE.cbl"), "--cut", str(tmp_path / "NOPE.cut")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock export: no such file" in out


def test_export_writes_default_output_next_to_program(tmp_path, capsys):
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        "           DISPLAY \"HI\".\n"
    )
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PROCESS\n')

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    output_path = tmp_path / "PROG.mainframe.cbl"
    assert output_path.exists()
    assert "wrote mainframe-compilable source" in out
    assert str(output_path) in out


def test_export_writes_to_explicit_output_path(tmp_path, capsys):
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        "           DISPLAY \"HI\".\n"
    )
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PROCESS\n')
    output_path = tmp_path / "custom.cbl"

    exit_code = main(
        ["export", str(cbl), "--cut", str(cut), "--output", str(output_path)]
    )
    assert exit_code == 0
    assert output_path.exists()


def test_export_keeps_process_cbl_directives_that_run_would_strip(tmp_path, capsys):
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       CBL APOST\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        "           DISPLAY \"HI\".\n"
    )
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PROCESS\n')

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    assert exit_code == 0
    output_text = (tmp_path / "PROG.mainframe.cbl").read_text()
    assert "CBL APOST" in output_text


def _export_example(tmp_path, name, program):
    exit_code = main(
        [
            "export",
            str(_EXAMPLES / name / f"{program}.cbl"),
            "--cut",
            str(_EXAMPLES / name / f"{program}.cut"),
            "--output",
            str(tmp_path / "out.cbl"),
        ]
    )
    assert exit_code == 0
    return (tmp_path / "out.cbl").read_text().upper()


# Structural guard, one example per boundary category that actually uses
# EXEC syntax: splicing already replaces every mocked boundary's real
# statement (build_site_dispatch/build_exec_trap), this pins that the
# export path doesn't reintroduce any. Checks for END-EXEC specifically,
# not the bare "EXEC SQL"/"EXEC CICS"/"EXEC DLI" substrings:
# splicer/sqlca.py's own explanatory comments (e.g. "*> EXEC SQL INCLUDE
# SQLCA replaced by...") legitimately contain "EXEC SQL" as harmless
# comment text, but only a live, uncommented multi-line EXEC block ever
# carries an END-EXEC -- every one of those blocks is fully replaced by
# splicing, so the terminator keyword is a clean, comment-proof signal.


def test_export_output_has_no_live_exec_sql_boundary_text(tmp_path):
    output_text = _export_example(tmp_path, "invupdt", "INVUPDT")
    assert "END-EXEC" not in output_text


def test_export_output_has_no_live_exec_cics_boundary_text(tmp_path):
    output_text = _export_example(tmp_path, "custinq", "CUSTINQ")
    assert "END-EXEC" not in output_text


def test_export_output_has_no_live_exec_dli_boundary_text(tmp_path):
    output_text = _export_example(tmp_path, "claimseg", "CLAIMSEG")
    assert "END-EXEC" not in output_text


def test_export_reports_refused_static_checks_and_writes_nothing(tmp_path, capsys):
    cbl = tmp_path / "BAD.cbl"
    cbl.write_text("this is not cobol\n")
    cut = tmp_path / "BAD.cut"
    cut.write_text('TESTSUITE "s"\n')

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock export: refused (" in out
    assert not (tmp_path / "BAD.mainframe.cbl").exists()


def test_export_never_imports_docker_toolchain(tmp_path):
    import sys

    saved = sys.modules.pop("mockymock.runtime.docker_toolchain", None)
    try:
        cbl = _EXAMPLES / "ordrproc" / "ORDRPROC.cbl"
        cut = _EXAMPLES / "ordrproc" / "ORDRPROC.cut"
        main(
            [
                "export",
                str(cbl),
                "--cut",
                str(cut),
                "--output",
                str(tmp_path / "out.cbl"),
            ]
        )
        assert "mockymock.runtime.docker_toolchain" not in sys.modules
    finally:
        if saved is not None:
            sys.modules["mockymock.runtime.docker_toolchain"] = saved
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_cli_export.py -v`
Expected: FAIL — `argparse` reports `invalid choice: 'export'` (no such subcommand yet)

- [ ] **Step 3: Generalize `_write_report_file`**

In `mockymock/cli/main.py`, change lines 54-66:

```python
def _write_report_file(command: str, flag: str, target: str, content: str) -> bool:
    """Write one of `run`'s optional --*-xml/--*-json/--*-out report files
    (or `export`'s --output). A bad parent directory (or any other
    OS-level write failure) used to escape as a raw traceback after an
    otherwise-successful run -- report it the same way
    `_check_input_files` reports a bad input path instead, and let the
    caller's own exit code stand on the actual outcome rather than on
    whether a report file happened to be writable."""
    try:
        Path(target).write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"mockymock {command}: could not write {flag} to {target}: {exc}")
        return False
    return True
```

Update its 4 existing call sites inside `_cmd_run`, each gaining `"run"` as
the new first argument, no other changes. Call site 1 (around line 444):

```python
    if args.junit_xml:
        _write_report_file(
            "run",
            "--junit-xml",
            args.junit_xml,
            format_junit_xml(suite_result, crash_detail=crash_detail),
        )
```

Call site 2 (around line 451):

```python
    if args.json_report:
        _write_report_file(
            "run",
            "--json-report",
            args.json_report,
            format_json_report(
                build_json_report(
                    suite_result,
                    cut_suite=suite,
                    crash_detail=crash_detail,
                    cut_file=str(cut_path),
                    program_file=str(source_path),
                )
            ),
        )
```

Call site 3 (around line 478):

```python
            _write_report_file(
                "run",
                "--coverage-json",
                args.coverage_json,
                format_coverage_json(
                    coverage_report,
                    mapped,
                    program_file=str(source_path),
                    instrumented_name=instrumented_path.name,
                ),
            )
```

Call site 4 (around line 492):

```python
            _write_report_file(
                "run", "--coverage-out", args.coverage_out, coverage_text + "\n"
            )
```

- [ ] **Step 4: Write `_cmd_export`**

Add to `mockymock/cli/main.py`, after `_cmd_lint` and before `_cmd_collect`:

```python
def _cmd_export(args: argparse.Namespace) -> int:
    """Write the instrumented source to a file, adjusted for a real
    fixed-format COBOL compile (e.g. z/OS) instead of GnuCOBOL-only. See
    docs/2026-08-03-mainframe-export-command-design.md. Docker-free:
    identical pre-splice pipeline to `run` (via run_static_checks),
    stopping before compile_source/run_binary."""
    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import find_terminator_plans
    from mockymock.cli.checks import run_static_checks
    from mockymock.cli.mainframe_export import (
        build_provenance_header,
        insert_provenance_header,
        restore_fixed_format_columns,
        wrap_long_display_lines,
    )
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import transform_data_division_exec

    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock export", source_path, cut_path):
        return 1

    checked = run_static_checks(
        source_path,
        cut_path,
        args.copybook_path,
        case_names=args.case,
        tag_names=args.tag,
        preserve_compiler_directives=True,
    )
    if checked.linkage is not None:
        _print_linkage_neutralization("export", checked.linkage, applied=True)
    if checked.problems:
        for problem in checked.problems:
            if problem.startswith("  "):
                print(problem)
            else:
                print(f"mockymock export: {problem}")
        return 1

    result = checked.parse_result
    suite = checked.suite
    surface = checked.surface
    lines = checked.lines
    scope_map = checked.scope_map
    linkage = checked.linkage
    assert (
        result is not None
        and suite is not None
        and surface is not None
        and lines is not None
        and scope_map is not None
    )  # implied by checked.problems being empty

    # Restore the 7 columns normalize_fixed_format stripped BEFORE
    # splicing: collect_boundaries/splice_program are line-granular, never
    # column-position-sensitive (verified empirically during design), so
    # this uniform prefix is transparent to them and matches the column
    # convention splicer-generated lines already assume.
    lines = restore_fixed_format_columns(lines)

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_plans, _ = find_terminator_plans(
        surface, result.ast, suite, scope_map, lines
    )
    flow_plans, _ = find_flow_mock_plans(result.ast, suite, lines)
    lines = splice_program(
        lines,
        boundaries,
        surface,
        suite,
        registry,
        terminator_plans,
        flow_plans,
        checked.file_status_fields,
        trace=False,
    )
    lines, _ = transform_data_division_exec(lines, copybook_paths=args.copybook_path)

    reset_lines = reset_move_lines(result.ast)
    if linkage is not None:
        reset_lines = reset_lines + extra_reset_lines(linkage)
    artifact = build_driver(suite, reset_lines, registry)
    instrumented = _insert_driver(lines, artifact)

    instrumented, overflow_problems = wrap_long_display_lines(instrumented)
    if overflow_problems:
        for problem in overflow_problems:
            print(f"mockymock export: refused (COLUMN_OVERFLOW): {problem}")
        return 1

    header = build_provenance_header(str(source_path), str(cut_path))
    instrumented = insert_provenance_header(instrumented, header)

    output_path = (
        Path(args.output)
        if args.output
        else source_path.with_suffix(".mainframe.cbl")
    )
    if not _write_report_file(
        "export", "--output", str(output_path), "\n".join(instrumented) + "\n"
    ):
        return 1

    print(
        f"mockymock export: wrote mainframe-compilable source "
        f"({len(suite.test_cases)} test case(s)) -> {output_path}"
    )
    _report_unsupported_boundaries(surface)
    return 0
```

- [ ] **Step 5: Wire `export_parser` into `build_parser()`**

Add to `mockymock/cli/main.py`, at the end of `build_parser()` (after
`dashboard_parser.set_defaults(func=_cmd_dashboard)`, before `return parser`):

```python
    export_parser = subparsers.add_parser(
        "export",
        help=(
            "Write the instrumented COBOL source to a file, adjusted for "
            "a real fixed-format COBOL compile (e.g. z/OS) instead of "
            "GnuCOBOL-only"
        ),
    )
    export_parser.add_argument("program")
    export_parser.add_argument("--cut", required=True)
    export_parser.add_argument("-o", "--output")
    export_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    export_parser.add_argument(
        "--case",
        action="append",
        help=(
            "Include only the TESTCASE with this exact name (repeatable; "
            "combines with --tag as a union)"
        ),
    )
    export_parser.add_argument(
        "--tag",
        action="append",
        help=(
            "Include only TESTCASEs carrying this tag (repeatable; "
            "combines with --case as a union)"
        ),
    )
    export_parser.set_defaults(func=_cmd_export)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_cli_export.py tests/unit/test_cli.py tests/unit/test_checks.py -v`
Expected: PASS (the new export tests, plus no regressions in existing CLI/checks tests)

- [ ] **Step 7: Run the full unit suite**

Run: `python -m pytest tests/unit -v`
Expected: PASS (no regressions anywhere — `_write_report_file`'s new required first
parameter is the one change with a wide blast radius; if any test breaks,
it means another call site was missed in Step 3)

- [ ] **Step 8: Commit**

```bash
git add mockymock/cli/main.py tests/unit/test_cli_export.py
git commit -m "feat(cli): add mockymock export subcommand"
```

---

### Task 5: Docker-gated integration test for the DISPLAY-wrap byte-identical guarantee

**Files:**
- Create: `tests/integration/test_export_display_wrap.py`

**Interfaces:**
- Consumes: `wrap_long_display_lines` (Task 2), `docker_toolchain.ensure_toolchain/compile_source/run_binary`, `sandbox_dir_maybe_kept` (all existing), `requires_docker` (existing, `tests/integration/_docker.py`).

- [ ] **Step 1: Write the test**

Create `tests/integration/test_export_display_wrap.py`:

```python
"""Docker-gated regression guard for the empirical finding behind
mockymock.cli.mainframe_export.wrap_long_display_lines (see
docs/2026-08-03-mainframe-export-command-design.md, Adjustment 2b):
splitting a long generated DISPLAY into `WITH NO ADVANCING` fragments
must not change what actually prints, or the __MOCKYMOCK__ stdout
protocol silently breaks."""
from mockymock.cli.mainframe_export import wrap_long_display_lines
from mockymock.runtime import docker_toolchain
from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
from tests.integration._docker import requires_docker

UNWRAPPED_LINE = (
    '           DISPLAY "__MOCKYMOCK__ CASE 001 FAIL: VERIFY SQL FETCH '
    'CUST_CURSOR WAS CALLED 3 TIMES, got " FUNCTION TRIM(UT-TALLY-EDITED)'
)


@requires_docker
def test_wrapped_display_produces_byte_identical_stdout():
    wrapped_lines, problems = wrap_long_display_lines([UNWRAPPED_LINE])
    assert not problems
    assert len(wrapped_lines) > 1  # actually exercised the wrap, not a no-op
    assert all(len(line) <= 72 for line in wrapped_lines)

    program_lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. WRAPCHK.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01  UT-TALLY-EDITED        PIC Z(8)9.",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        "           MOVE 3 TO UT-TALLY-EDITED",
        '           DISPLAY "===UNWRAPPED==="',
        UNWRAPPED_LINE,
        '           DISPLAY "===WRAPPED==="',
        *wrapped_lines,
        '           DISPLAY "===END==="',
        "           STOP RUN.",
    ]
    source = "\n".join(program_lines) + "\n"

    docker_toolchain.ensure_toolchain()
    with sandbox_dir_maybe_kept(root=docker_toolchain.WORK_ROOT, keep=False) as tmp:
        src = tmp / "WRAPCHK.cbl"
        src.write_text(source, encoding="utf-8", newline="\n")
        compiled = docker_toolchain.compile_source(src)
        assert compiled.success, compiled.stderr
        executed = docker_toolchain.run_binary(compiled.binary_path)
        assert executed.exit_code == 0

    stdout_lines = executed.stdout.splitlines()
    unwrapped_out = stdout_lines[stdout_lines.index("===UNWRAPPED===") + 1]
    wrapped_out = stdout_lines[stdout_lines.index("===WRAPPED===") + 1]
    assert wrapped_out == unwrapped_out
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/integration/test_export_display_wrap.py -v`
Expected: PASS if Docker is reachable; SKIPPED with reason "Docker daemon not
reachable" otherwise (matches every other file in `tests/integration/`)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_export_display_wrap.py
git commit -m "test(integration): pin the DISPLAY-wrap byte-identical-output guarantee"
```

---

### Task 6: OKF and README documentation

**Files:**
- Modify: `.okf/cli.md`
- Modify: `.okf/index.md`
- Modify: `.okf/log.md`
- Modify: `README.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Update `.okf/cli.md`**

In the file's frontmatter (line 4), change:
```
description: argparse entry point (setup, generate, run, debug, mutate, lint, collect, dashboard) that orchestrates the splicer, GnuCOBOL runtime, and report formatters.
```
to:
```
description: argparse entry point (setup, generate, run, debug, mutate, lint, collect, dashboard, export) that orchestrates the splicer, GnuCOBOL runtime, and report formatters.
```

In the Overview section (lines 11-30), update the subcommand count/list and
the ASCII pipeline diagram:
```
`mockymock/cli/main.py` is the single argparse-based entry point (`prog="mockymock"`,
`--version` from `mockymock.__version__`). It defines nine subcommands —
`setup`, `generate`, `run`, `debug`, `mutate`, `lint`, `collect`, `dashboard`, `export` — each wired via `set_defaults(func=...)` and
```
and add a line to the pipeline diagram after the `dashboard` line:
```
mockymock export   -> cli.checks (static) -> splicer -> cli.mainframe_export (no Docker)
```

Add a new `## mockymock export` subsection (after the `## mockymock dashboard`
section, before `# Gotchas`), summarizing: the Docker-free pipeline reuse,
the three adjustments (directive preservation, column restoration/wrap,
provenance header), and the default output path — cross-reference
`docs/2026-08-03-mainframe-export-command-design.md` for the full empirical
basis rather than duplicating it.

- [ ] **Step 2: Update `.okf/index.md`**

Change line 22:
```
* [CLI](cli.md) — `mockymock setup` / `generate` / `run` / `debug` / `mutate` / `lint` / `collect` / `dashboard` and how each orchestrates the modules above
```
to:
```
* [CLI](cli.md) — `mockymock setup` / `generate` / `run` / `debug` / `mutate` / `lint` / `collect` / `dashboard` / `export` and how each orchestrates the modules above
```

- [ ] **Step 3: Append a dated entry to `.okf/log.md`**

Add an entry (newest-first, per the file's existing convention — check the
top of the file for the exact format to match) noting: `mockymock export`
added, Docker-free, reuses `run`'s splice pipeline with three z/OS-portability
adjustments; empirical basis in
`docs/2026-08-03-mainframe-export-command-design.md`.

- [ ] **Step 4: Update `README.md`**

In the "Beyond pass/fail" list (around line 130-136), add one line after the
`dashboard` entry:
```
- `mockymock export` — write the instrumented source to a file, adjusted for a real fixed-format (z/OS) COBOL compile instead of GnuCOBOL-only; validates the computational core against a real IBM compiler, not real I/O ([details](docs/2026-08-03-mainframe-export-command-design.md))
```

- [ ] **Step 5: Validate the OKF bundle**

Run: `/okf:validate .okf --strict` (per this workspace's standing OKF
instruction) and resolve every error before committing.

- [ ] **Step 6: Commit**

```bash
git add .okf/cli.md .okf/index.md .okf/log.md README.md
git commit -m "docs: document mockymock export in the OKF bundle and README"
```

---

### Task 7: VS Code command — `resolveCutPath` + export module

**Files:**
- Modify: `mocky-mock-vscode-extension/src/discovery/cutDiscovery.ts`
- Modify: `mocky-mock-vscode-extension/src/discovery/cutDiscovery.test.ts`
- Create: `mocky-mock-vscode-extension/src/export/exportMainframe.ts`
- Create: `mocky-mock-vscode-extension/src/export/exportMainframe.test.ts`

**Interfaces:**
- Consumes: `CommandRunner`/`runCommand` (`../environment/commandRunner`), `resolveExecutablePath` (`../environment/checks`), `resolveCblPath` (`../discovery/cutDiscovery`, existing).
- Produces: `resolveCutPath(cblFilePath: string): string`; `buildExportArgs(cblPath, cutPath, copybookPaths, outputPath): string[]`; `runExport(executablePath, cblPath, cutPath, copybookPaths, outputPath, run): Promise<ExportResult>`; `activateExportMainframeCommand(context): void`.

- [ ] **Step 1: Write the failing test for `resolveCutPath`**

Add to `mocky-mock-vscode-extension/src/discovery/cutDiscovery.test.ts`
(find the existing `resolveCblPath` test block and add a sibling):

```typescript
describe('resolveCutPath', () => {
  it('swaps a .cbl path for its sibling .cut', () => {
    assert.strictEqual(resolveCutPath('/p/PROG.cbl'), '/p/PROG.cut');
  });
});
```

Add `resolveCutPath` to the existing `import { ... } from './cutDiscovery'`
line at the top of the test file.

- [ ] **Step 2: Run the test to verify it fails**

Run (from `mocky-mock-vscode-extension/`): `npm run test:unit`
Expected: FAIL — `resolveCutPath` is not exported yet

- [ ] **Step 3: Add `resolveCutPath`**

In `mocky-mock-vscode-extension/src/discovery/cutDiscovery.ts`, add right
after the existing `resolveCblPath` function (line 157-160):

```typescript
export function resolveCutPath(cblFilePath: string): string {
  const parsed = path.parse(cblFilePath);
  return path.join(parsed.dir, `${parsed.name}.cut`);
}
```

- [ ] **Step 4: Write the failing tests for the export module**

Create `mocky-mock-vscode-extension/src/export/exportMainframe.test.ts`:

```typescript
import * as assert from 'assert';
import { buildExportArgs, runExport } from './exportMainframe';
import { CommandRunner } from '../environment/commandRunner';

describe('buildExportArgs', () => {
  it('builds the base export invocation with no copybook paths', () => {
    const args = buildExportArgs('/p/PROG.cbl', '/p/PROG.cut', [], '/p/PROG.mainframe.cbl');
    assert.deepStrictEqual(args, [
      'export', '/p/PROG.cbl', '--cut', '/p/PROG.cut', '--output', '/p/PROG.mainframe.cbl',
    ]);
  });

  it('appends a --copybook-path flag per configured path', () => {
    const args = buildExportArgs('/p/PROG.cbl', '/p/PROG.cut', ['/copy/a', '/copy/b'], '/p/PROG.mainframe.cbl');
    assert.deepStrictEqual(args, [
      'export', '/p/PROG.cbl', '--cut', '/p/PROG.cut', '--output', '/p/PROG.mainframe.cbl',
      '--copybook-path', '/copy/a', '--copybook-path', '/copy/b',
    ]);
  });
});

describe('runExport', () => {
  it('returns exit code and output on success', async () => {
    const fakeRun: CommandRunner = async (cmd, args) => {
      assert.strictEqual(cmd, 'mockymock');
      assert.ok(args.includes('export'));
      return {
        code: 0,
        stdout: 'mockymock export: wrote mainframe-compilable source (1 test case(s)) -> /p/PROG.mainframe.cbl\n',
        stderr: '',
      };
    };
    const result = await runExport('mockymock', '/p/PROG.cbl', '/p/PROG.cut', [], '/p/PROG.mainframe.cbl', fakeRun);
    assert.strictEqual(result.exitCode, 0);
    assert.match(result.stdout, /wrote mainframe-compilable source/);
  });

  it('surfaces a refusal on nonzero exit', async () => {
    const fakeRun: CommandRunner = async () => ({
      code: 1,
      stdout: '',
      stderr: 'mockymock export: refused (COLUMN_OVERFLOW): line 42 ...\n',
    });
    const result = await runExport('mockymock', '/p/PROG.cbl', '/p/PROG.cut', [], '/p/PROG.mainframe.cbl', fakeRun);
    assert.strictEqual(result.exitCode, 1);
    assert.match(result.stderr, /COLUMN_OVERFLOW/);
  });
});
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `npm run test:unit`
Expected: FAIL — `./exportMainframe` module doesn't exist yet

- [ ] **Step 6: Write the implementation**

Create `mocky-mock-vscode-extension/src/export/exportMainframe.ts`:

```typescript
import * as vscode from 'vscode';
import * as path from 'path';
import { CommandRunner, runCommand } from '../environment/commandRunner';
import { resolveExecutablePath } from '../environment/checks';
import { resolveCblPath, resolveCutPath } from '../discovery/cutDiscovery';

export function buildExportArgs(
  cblPath: string,
  cutPath: string,
  copybookPaths: string[],
  outputPath: string
): string[] {
  const args = ['export', cblPath, '--cut', cutPath, '--output', outputPath];
  for (const p of copybookPaths) args.push('--copybook-path', p);
  return args;
}

export interface ExportResult {
  exitCode: number;
  stdout: string;
  stderr: string;
}

export async function runExport(
  executablePath: string,
  cblPath: string,
  cutPath: string,
  copybookPaths: string[],
  outputPath: string,
  run: CommandRunner
): Promise<ExportResult> {
  const args = buildExportArgs(cblPath, cutPath, copybookPaths, outputPath);
  const result = await run(executablePath, args);
  return { exitCode: result.code, stdout: result.stdout, stderr: result.stderr };
}

function defaultOutputPath(cblPath: string): string {
  const parsed = path.parse(cblPath);
  return path.join(parsed.dir, `${parsed.name}.mainframe.cbl`);
}

// One-shot palette action (like mockymock.checkEnvironment), not wired
// into the Testing API tree: it produces one artifact per program/cut
// pair, not a per-test-case result. v1 requires an active .cbl or .cut
// editor -- no quick-pick fallback across every discovered suite, kept
// deliberately out of scope (see docs/2026-08-03-mainframe-export-
// command-design.md's Alternatives Considered).
export function activateExportMainframeCommand(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand('mockymock.exportMainframe', async () => {
      const editor = vscode.window.activeTextEditor;
      const activePath = editor?.document.uri.fsPath;
      let cblPath: string;
      let cutPath: string;
      if (activePath?.endsWith('.cut')) {
        cutPath = activePath;
        cblPath = resolveCblPath(activePath);
      } else if (activePath?.endsWith('.cbl')) {
        cblPath = activePath;
        cutPath = resolveCutPath(activePath);
      } else {
        vscode.window.showErrorMessage(
          'mockymock: open a .cbl or .cut file first, then run "Export Mainframe-Ready COBOL".'
        );
        return;
      }

      const workspaceFolder = vscode.workspace.getWorkspaceFolder(editor!.document.uri);
      const config = vscode.workspace.getConfiguration('mockymock', editor!.document.uri);
      const executablePath = resolveExecutablePath(config.get<string>('executablePath'), context.extensionPath);
      const copybookPaths = (config.get<string[]>('copybookPaths') ?? []).map((p) =>
        workspaceFolder && !path.isAbsolute(p) ? path.join(workspaceFolder.uri.fsPath, p) : p
      );
      const outputPath = defaultOutputPath(cblPath);

      const result = await runExport(executablePath, cblPath, cutPath, copybookPaths, outputPath, runCommand);
      if (result.exitCode !== 0) {
        vscode.window.showErrorMessage(`mockymock export failed:\n${result.stdout}${result.stderr}`);
        return;
      }
      const doc = await vscode.workspace.openTextDocument(outputPath);
      await vscode.window.showTextDocument(doc);
      vscode.window.showInformationMessage(`mockymock: exported mainframe-ready source to ${outputPath}`);
    })
  );
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm run test:unit`
Expected: PASS (all tests, including the new `resolveCutPath`/`buildExportArgs`/`runExport` ones)

- [ ] **Step 8: Run the type checker**

Run: `npm run check-types`
Expected: no errors

- [ ] **Step 9: Commit**

```bash
git add src/discovery/cutDiscovery.ts src/discovery/cutDiscovery.test.ts src/export/exportMainframe.ts src/export/exportMainframe.test.ts
git commit -m "feat: add mockymock.exportMainframe command"
```
(Run this `git add`/`git commit` from `mocky-mock-vscode-extension/`, a
separate git repository from `mocky-mock/`.)

---

### Task 8: Register the command and update `package.json`

**Files:**
- Modify: `mocky-mock-vscode-extension/package.json`
- Modify: `mocky-mock-vscode-extension/src/extension.ts`

**Interfaces:**
- Consumes: `activateExportMainframeCommand` (Task 7).

- [ ] **Step 1: Add the command contribution**

In `mocky-mock-vscode-extension/package.json`, change the `contributes.commands`
array (lines 25-31) from:
```json
    "commands": [
      {
        "command": "mockymock.checkEnvironment",
        "title": "Check Environment Status",
        "category": "mockymock"
      }
    ],
```
to:
```json
    "commands": [
      {
        "command": "mockymock.checkEnvironment",
        "title": "Check Environment Status",
        "category": "mockymock"
      },
      {
        "command": "mockymock.exportMainframe",
        "title": "Export Mainframe-Ready COBOL",
        "category": "mockymock"
      }
    ],
```

- [ ] **Step 2: Register it in `extension.ts`**

In `mocky-mock-vscode-extension/src/extension.ts`, add the import (after
line 7's `MockymockDebugConfigurationProvider` import):

```typescript
import { activateExportMainframeCommand } from './export/exportMainframe';
```

And add the call inside `activate()` (after line 14's
`activateLintDiagnostics(context);`):

```typescript
  activateExportMainframeCommand(context);
```

- [ ] **Step 3: Compile and smoke-check**

Run (from `mocky-mock-vscode-extension/`): `npm run compile`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add package.json src/extension.ts
git commit -m "feat: register Export Mainframe-Ready COBOL in the command palette"
```

---

## Final verification (after all tasks)

- [ ] Run the full mockymock unit suite: `python -m pytest tests/unit -v` — expect all green.
- [ ] Run the full mockymock integration suite (Docker required for full coverage): `python -m pytest tests/integration -v` — expect all green or cleanly skipped.
- [ ] Run the VS Code extension's test suite: `npm run test:unit` (from `mocky-mock-vscode-extension/`) — expect all green.
- [ ] Manually export one real example end-to-end: `mockymock export examples/custprog/CUSTPROG.cbl --cut examples/custprog/CUSTPROG.cut -o /tmp/CUSTPROG.mainframe.cbl` (or a scratch path) and read the output file — confirm the provenance header is present, no line exceeds 72 columns, and `CBL`/`PROCESS` directives (if you add one to a scratch copy) survive.
- [ ] Use the `superpowers:requesting-code-review` skill before merging.
