# `export`: continue a long literal instead of refusing it

Extends [2026-08-03-mainframe-export-command-design.md](2026-08-03-mainframe-export-command-design.md)'s
Adjustment 2 (column-72 overflow). That adjustment could wrap exactly one
shape — a mockymock-generated `DISPLAY` — and refused everything else long,
fail-closed. This note covers the second wrapping path added on 2026-09-04.

## The report

`mockymock export` on a real 52-boundary program (`DTBC7D01.cbl`) refused
with 52 `COLUMN_OVERFLOW` problems. Fifty were the documented,
user-fixable trigger: `.cut` MOCK body text that `injector.py` re-indents
by 19 columns when splicing it in, shortened by hand in the `.cut` file.

The last two were not fixable from the `.cut` file at all. They came from
the program's own declarations:

```cobol
       01  DEBUT-WORKING-STORAGE   PIC X(44) VALUE
           "***** DEBUT WORKING-STORAGE DTBC7D01 ******".
       ...
       01  FIN-WORKING-STORAGE     PIC X(44) VALUE
           "***** FIN   WORKING-STORAGE DTBC7D01 ******".
```

Storage-dump boundary markers — standard practice in IBM shops, declared
and never referenced. `splicer/reset.py` re-serializes *every*
WORKING-STORAGE `VALUE` clause into `UT-RESET-WORKING-STORAGE` as a
single-line `MOVE`, and at 11 columns of indent plus a 21-character target
name that `MOVE` is 85 columns wide. Unconditional: it happens even when
`--case` restricts the run to one `TESTCASE`, because the reset paragraph
covers the whole section regardless. No CLI flag skips it.

So the only available remedy was editing production COBOL — a
behaviorally-inert change (shortening a banner string) to a file nobody
asked to touch, to work around a limitation in the tool. That is the wrong
side of the trade: the tool should emit COBOL the target compiler accepts.

## The fix

Fixed-format COBOL has had the mechanism since forever — continuation
lines. `wrap_long_literal_lines` splits the single quoted literal of any
still-too-long line across them:

```cobol
           MOVE              "***** DEBUT WORKING-STORAGE DTBC7D01 *****
      -    "*" TO DEBUT-WORKING-STORAGE
```

`-` in the indicator area (column 7), the literal re-opened at column 12
(Area B, as both IBM Enterprise COBOL and GnuCOBOL require). The statement
is the same statement and the literal's content is byte-for-byte what it
was — nothing about the program's meaning changes, which is what makes
this preferable to the alternatives considered (splitting into
reference-modified `MOVE`s, or a `MOVE SPACES` + `STRING ... DELIMITED BY
SIZE`: both change one statement into several with subtly different
truncation/justification semantics).

`fit_within_columns` is now the single entry point `_cmd_export` calls. It
runs the `DISPLAY` pass first — that pass's byte-identical-stdout
equivalence is empirically established and the `__MOCKYMOCK__` protocol
rides on it — then the literal pass over whatever is still long, and
reports only lines *neither* can fit.

### Every continued line is filled to exactly column 72

Not cosmetic, and the one detail a future simplification must not
"tidy away". Under fixed-format rules every character through column 72 of
a continued line belongs to the open literal, **trailing blanks included**.
Verified both directions against real GnuCOBOL 4.0 (`cobc -x -fixed`):

| Split | Value read back from `PIC X(42)` |
|---|---|
| continued line filled to exactly column 72 | `***** DEBUT WORKING-STORAGE DTBC7D01 ******` |
| same split, continued line left short | `***** DEBUT WORKING-S` + 22 spaces (truncated) |

Filling exactly is always achievable because the padding goes in the
*prefix*, before the opening delimiter, where extra spaces are only
separators: the chunk is chosen first (whole `_atomic_units` only, so a
doubled delimiter is never bisected — the same unit-based rule Adjustment 2
already needed) and the line is then padded up to the limit. Both facts are
pinned by `tests/integration/test_export_literal_continuation.py`, which
compiles the correct and the short-filled split side by side in one
program.

### Second bug fixed by the same change

A literal the *original* source already continued reaches `export` as one
long line: cobolparser's `normalize_fixed_format` merges continuation lines
when it normalizes to free form, and `restore_fixed_format_columns` then
pushes the merged line 7 columns further right. That refused too, on
programs with no long `.cut` text anywhere. Re-continuing the literal
restores what the source itself had.

## What still refuses

Fail-closed, unchanged in spirit — a line that cannot be brought under the
limit is reported, never silently shipped long:

- no quoted literal on the line (nothing to split);
- two literals (which to split is ambiguous — a wrong guess is a silently
  different program);
- non-literal text that alone overflows (the final continuation line still
  has to carry it);
- a `CBL`/`PROCESS` compiler-directing statement, read before continuation
  rules apply.

The refusal hint now points at identifier names rather than "shorten the
literal", which is no longer the remedy.

## Empirical basis

- GnuCOBOL 4.0, `cobc -x -fixed -std=mvs`, both facts in the table above.
- 400 randomized shapes (both delimiters, escaped-delimiter pairs, literal
  lengths 1-180, indents 11/12/19/30, varying target-name lengths, optional
  trailing period): 342 exceeded 72 columns and were wrapped, all 342
  compiled and read back byte-identically, zero refusals, zero column
  overflow warnings under `-Wcolumn-overflow`. The same generator is the
  standing zero-dependency guard in
  `tests/unit/test_mainframe_export.py::test_continuation_round_trips_under_randomized_shapes`.
- The reported program's shape end-to-end: `mockymock export` on a
  `DEBUT-/FIN-WORKING-STORAGE` fixture now writes a file that compiles
  clean in fixed format and whose 5 test cases pass.
- As with Adjustment 2, no IBM Enterprise COBOL compiler is reachable from
  this environment; the provenance header names that residual explicitly.
