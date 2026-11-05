---
type: Module
title: DSL (.cut test files)
description: MockTestSuite/MockTestCase/MockDirective model, the parser that reads .cut text into it, and the generator that scaffolds .cut files from a MockSurface.
tags: [dsl, parser, cut-file]
timestamp: 2026-10-16T20:00:00Z
---

# Overview

`mockymock/dsl/` is the DSL layer for `.cut` test files: a small text format
that says which COBOL boundaries to mock, what to move into working-storage
before running, which paragraph to `PERFORM`, and what to assert after.

```
.cut text ──▶ parser.py: parse_cut() ──▶ model.py: MockTestSuite
                                                │
                             (consumed by splicer/ to instrument COBOL)

MockSurface (static analysis) ──▶ generator.py: scaffold_cut() ──▶ starter .cut text
```

`model.py` holds no behavior beyond `describe()` and `all_mock_keys()` — it's
the shared vocabulary between the parser (produces it), the generator
(also produces it, indirectly, as text), and the splicer (consumes it).

# Grammar

```
TESTSUITE "<name>"
[ PROGRAM "<path to the program, relative to this .cut>" ]

[ PROVIDER <name>
      HEADER <col>, ... [, <col>]*
      ROW <value>, ... [, <value>]* [ ROW ... ]* ]*

TESTCASE "<name>" [ TAGS "<tag>" ... ] [ USING PROVIDER <name> ]
    [ MOCK <category> <key>
          <COBOL statement lines, passed through verbatim>
      END-MOCK ]*
    [ [ MOVE <value> TO <target> ]*
      PERFORM <paragraph> [ THRU|THROUGH <paragraph> ] ]*   (earlier calls)
    [ MOVE <value> TO <target> ]*
    PERFORM <paragraph> [ THRU|THROUGH <paragraph> ]
    [ EXPECT <data-name> [NOT] TO BE [GREATER|LESS THAN [OR EQUAL TO]] <value> ]*
    [ VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation> ]*
```

- Exactly one `TESTSUITE` per file — a second `TESTSUITE` line raises
  `CutParseError` with its line number (it used to silently discard every
  previously parsed test case, so concatenated .cut files ran only the
  last suite).
- `PROGRAM "<path>"` (2026-10-14) is optional, at most once, and only
  directly after `TESTSUITE` (before any TESTCASE, hook or PROVIDER); it
  sets `MockTestSuite.program_path`/`program_line`. The parser only stores
  it -- pairing is `cli/discovery.py`'s job, which reads the line from raw
  text (`read_program_line`) so a suite with a later syntax error still
  pairs. See [cli](cli.md).
- `TESTCASE` must follow a `TESTSUITE`; `MOCK`/`MOVE`/`PERFORM`/`EXPECT`/`VERIFY`
  must all be inside a `TESTCASE`. Violating order raises `CutParseError` at
  the offending line.
- Several `PERFORM`s make a multi-call case (2026-10-25): every `MOVE` and
  `PERFORM` above the last `PERFORM` becomes a `HookStep` on
  `MockTestCase.steps` (`parser._close_call`), run in order after
  BEFORE-EACH and before the case's own `setup_moves`, with the case's
  mocks; `UT-EARLY-EXIT` is reset after each step PERFORM. VERIFY counts
  every call of the case. `hook_checks()` gates each step PERFORM as hook
  `"TESTCASE"`, and a case mock no call reaches is refused
  `UNMATCHED_MOCK` after all of them (`cli.checks`). A `MOVE` or
  `PERFORM` below an `EXPECT`/`VERIFY` raises (`after an EXPECT/VERIFY`),
  as does a `MOVE` after the last `PERFORM`.
- `<expectation>` is validated **at parse time**: `ONCE`, `NEVER`,
  `AT LEAST ONCE`, or `<n> TIMES` (case-insensitive), matching exactly what
  `splicer/driver.py`'s `_verify_condition` compiles — anything else raises
  `CutParseError` with the .cut line number instead of exploding later in
  codegen as a raw `ValueError`. Keep `_validate_expectation` (parser) and
  `_verify_condition` (driver) in sync.
- Lines starting with `*>` are comments **outside** a `MOCK` body; inside a
  body they pass straight through as valid free-form COBOL (a mock body can
  legitimately contain a COBOL comment).
- Blank lines are always skipped.
- `TAGS "<tag>" ["<tag>" ...]` after the TESTCASE name attaches selection
  tags (`run --tag`, `collect --json`, the JSON run report). Tags have no
  runtime semantics; an empty (`""`/blank) tag raises `CutParseError`.
  `TAGS` may come before or after `USING PROVIDER` (`_TESTCASE_RE`'s
  `tags` / `tags_after` groups, #329) -- written after it, the line used to
  match nothing and, under an open PROVIDER, was reported as "not allowed
  inside PROVIDER"; two TAGS lists on one line raise `CutParseError`.
- The parser records 1-based `.cut` line numbers on the model: `MockTestSuite
  .line`, `MockTestCase.line`, `ExpectDirective.line`, `VerifyDirective.line`
  (all default 0 for hand-built models). Editor integrations rely on these
  for navigation and failure locations — keep them accurate when touching
  the parse loop.
- `EXPECT` supports negation and comparison phrases: `EXPECT <name>
  [NOT] TO BE [GREATER THAN|LESS THAN [OR EQUAL TO]] <value>`. Each
  phrase normalizes at parse time to one canonical COBOL relation
  operator on `ExpectDirective.operator` (`model.EXPECT_OPERATORS`:
  `=`, `NOT =`, `>`, `NOT >`, `<`, `NOT <`, `>=`, `NOT >=`, `<=`,
  `NOT <=`); plain `TO BE` stays `=`, so pre-operator `.cut` files and
  hand-built directives are unchanged. `splicer/driver.py`'s
  `_EXPECT_FAIL_CONDITIONS` compiles each operator's *negation* into the
  generated `IF` (the IF guards the failure branch; `>=`/`<=` negate to
  the equivalent plain `<`/`>` to keep emitted conditions to the
  simplest COBOL-85 relational forms) — keep that map in sync with
  `EXPECT_OPERATORS`. A value carrying an unquoted `AND`/`OR`
  (`TO BE GREATER THAN 0 AND < 10`, `TO BE 7 OR 8`) is an abbreviated combined
  condition; the driver negates it whole, `IF NOT (<name> <op> <value>)`
  (issue #265) -- except for a negated operator (`NOT TO BE 7 OR 8`),
  whose NOT COBOL would carry onto every abbreviated relation in the
  tail, so its guard is the un-negated condition, `IF (<name> = 7 OR 8)`
  (issue #339). The FAIL `DISPLAY` carries the operator between
  name and value (`expected WS-X > 5, got ...`), and
  `report/json_report.py`'s `_EXPECT_HEAD_RE` splits attribution on it
  (`expected` field keeps the bare value for `=`, is operator-prefixed
  otherwise). Fail-closed: a dangling phrase (`TO BE GREATER 5`,
  `... OR EQUAL 5`) raises `CutParseError` at the line instead of
  splicing leftover words into the generated IF
  (`_EXPECT_DANGLING_PHRASE_RE`, whole-word so `GREATER-VALUE` still
  parses as an ordinary value). A value starting with a relational symbol
  (`TO BE > 0 AND < 10`, which plain `TO BE` read as `= > 0 ...`) is
  refused the same way, also when a PROVIDER row substitutes it
  (`_reject_dangling_phrase`, 2026-10-26); symbols stay legal in the tail. Likewise an EXPECT value ending in a
  period outside quotes (`EXPECT WS-X TO BE 5.`, the COBOL sentence habit)
  raises `CutParseError` (`_reject_sentence_period`, 2026-09-27) --
  spliced into the generated `IF`, the period ended the sentence mid-IF
  and `cobc` rejected the driver while `lint` passed; a PROVIDER row
  substituting such a value is refused at its `ROW` line. The same check
  covers setup and BEFORE-*/AFTER-* hook `MOVE` values, and PROVIDER rows
  substituted into them (issue #197, 2026-10-16). Phrase words are case-sensitive
  uppercase like every other keyword.
- `EXPECT <numeric-edited field> [NOT] TO BE [<comparison>] <unquoted
  number>` compares the de-edited value (issue #350): a numeric-edited
  item compares as its edited text, so `TO BE 100.00` never matched
  `"      100.00"`. `driver._compares_by_value` picks these (the leaf name
  is in `record_rewrite.numeric_edited_fields`, from the PICTURE via
  `is_numeric_edited_picture`; the value is a plain signed decimal, its
  point a period or, for a `DECIMAL-POINT IS COMMA` program, a comma; no
  reference modification), and the driver emits `MOVE <field> TO
  UT-DEEDIT-VALUE` (`PIC S9(18)V9(13)`, the de-editing MOVE, verified
  under GnuCOBOL with CR/DB, `*` and `$`) then the relation on that.
  A quoted value, a data-name or a combined condition keeps the direct
  compare. The FAIL line still shows the edited text.
- `EXPECT <88-name> [NOT] TO BE TRUE|FALSE` tests a level-88
  condition-name (issue #189). TRUE/FALSE are not values any data item
  compares with, so `driver._condition_name_truth` emits `IF NOT <name>`
  / `IF <name>` instead of the relational `IF FLAG-ON NOT = TRUE`, which
  cobc rejected ("condition-name not allowed here"); an 88 cannot be
  DISPLAYed, so the FAIL line reports the truth value it had (`expected
  FLAG-ON = TRUE, got FALSE`). TRUE/FALSE after an ordering phrase
  (`TO BE GREATER THAN TRUE`) is a `CutParseError`. The target is not
  checked statically: a non-88 name still fails at compile time.
- `EXPECT <data-name> TO BE <value>`'s `<data-name>` and `MOVE <value> TO
  <target>`'s `<target>` both accept one non-nested `(...)` group appended
  to an identifier — a table subscript (`WS-TABLE(1, 1)`, `WS-TABLE(1 1)`,
  `WS-TABLE(1,1)` all parse) or reference modification (`FIELD(1:5)`).
  The name may be qualified the COBOL way, `CUST-ID OF OUT-REC` /
  `CUST-TAB IN OUT-REC (2)` (subscript after the qualifiers), spliced
  verbatim -- the only way to name a field declared under two records
  (issue #252); `cut_names` checks every word, `CAPTURE ... INTO` and
  `*> STUB EXPECT` take the same shape, and `record_rewrite` looks the
  PICTURE up by the leading word. Nested parens are unsupported and fail
  closed (`unrecognized statement`) rather than being mis-parsed. Both regexes
  share the `_SUBSCRIPTED_NAME` fragment in `parser.py`, which falls back to
  plain `\S+` for non-identifier tokens — that's what lets a literal
  `{Placeholder}` name (see `PROVIDER` below — data-names/MOVE-targets are
  deliberately never substituted) keep parsing verbatim. `PERFORM`'s target
  stays plain `\S+`: a paragraph/section name is never subscripted.

### Suite hooks: `BEFORE-ALL` / `BEFORE-EACH` / `AFTER-EACH` / `AFTER-ALL`

At most one of each per `TESTSUITE`, all after the `TESTSUITE` header and
before the first `TESTCASE`. `BEFORE-*` close with `END-BEFORE`, `AFTER-*`
with `END-AFTER` (the wrong one is a parse error naming the right one).
Design: `docs/2026-10-10-suite-hooks-design.md`.

**Steps** (2026-10-10): `MOVE <value> TO <target>` and `PERFORM <para>
[THRU <para>]` lines in any of the four blocks become `HookStep`s, in
order, on `MockTestSuite.before_all_steps` / `before_each_steps` /
`after_each_steps` / `after_all_steps`. The driver runs them at JUnit's
points: BEFORE-ALL once before the first case, then `UT-SAVE-STATE`;
each case `UT-RESET-WORKING-STORAGE` + `UT-RESTORE-STATE` (only when
BEFORE-ALL has steps), BEFORE-EACH steps before the case's own `MOVE`s,
AFTER-EACH steps after its `EXPECT`/`VERIFY`; AFTER-ALL once after the
last case. BEFORE-ALL/AFTER-ALL run with `UT-CURRENT-CASE` =
`SUITE_PHASE_ID` (`"SUITE"`), answered by `before_all_mocks`
(`injector.dispatch_entries`); EACH steps run inside the case with its
mocks. When BEFORE-EACH has a `PERFORM`, the case's tallies are zeroed
again after it, so `VERIFY` counts only the case's own `PERFORM`.
`UT-EARLY-EXIT` is reset to `"N"` after BEFORE-EACH's steps and before
AFTER-EACH's whenever that block has a `PERFORM`: a terminator reached
on one side must not cut the other short (hook paragraphs on a
terminator chain check the flag too).
`EXPECT`/`VERIFY` stay TESTCASE-only. See [splicer](splicer.md)'s
"BEFORE-ALL state snapshot".

**Static checks**: `MockTestSuite.hook_checks()` turns each hook
`PERFORM` into a synthetic `MockTestCase` (EACH hooks once per test
case), and `analysis_cases()` = test cases + those. `cli.checks` runs
`check_test_case` on each (problems prefixed `BEFORE-ALL PERFORM X:`,
deduplicated across cases, fix hint `Add to BEFORE-ALL:`/`BEFORE-EACH:`;
every mock in force counts as `shared` there, the case's own included,
since only the case's own check decides whether its mock is unmatched);
`union_executed_paragraphs`, `find_terminator_plans` and `flow_mocks`
iterate `analysis_cases()` so hook entry points count everywhere a case
entry point does.

**Mocks**: bodies of `BEFORE-*` may also hold `MOCK` directives (not
`AFTER-*` -- a parse error that says where to declare it). They are
desugared at parse time into every `TESTCASE`'s own `mocks` list;
precedence on a `(category, key)` collision is `TESTCASE` >
`BEFORE-EACH` > `BEFORE-ALL`, silently. The same directive objects stay
on `suite.before_all_mocks` / `before_each_mocks`. A shared mock is a
default: `check_test_case(shared=..., matched_out=...)` no longer
refuses one a given case doesn't reach; `cli.checks` refuses it
(`UNMATCHED_MOCK`, "not reached by any test case or hook step") only
when nothing reaches it (2026-10-10; before, every case had to reach
every shared mock). "Nothing" means the whole suite, not a `--case`/`--tag`
selection: when the selected cases leave a shared mock unmatched, the
unselected cases are checked for their matches only (their own refusals
are discarded), so selecting a case never refuses a clean suite (issue
#250). See
`docs/2026-07-20-before-blocks-and-file-status-design.md`.

### `FILE-STATUS IS <mnemonic-or-code>`

Usable once inside a `MOCK OPEN|CLOSE|READ|DELETE|START|UNLOCK|WRITE|REWRITE`
body. WRITE/REWRITE key on the record name, which resolves to its FD's
status field (issue #221). `<mnemonic>` is one of `SUCCESS`, `END-OF-FILE`,
`DUPLICATE-KEY`, `RECORD-NOT-FOUND`, `FILE-NOT-FOUND`, `ALREADY-OPEN`,
`NOT-OPEN`, `NO-CURRENT-RECORD`; a quoted two-character literal (e.g.
`"92"`) always works too. Every eligible category also gets an implicit
`MOVE "00"` (default success) before the mock's own body whenever the
target file declares a `FILE STATUS` field, whether or not
`FILE-STATUS IS` is used. See
`docs/2026-07-20-before-blocks-and-file-status-design.md`.

Fail-closed on malformed input: any mock-body line that starts with the
`FILE-STATUS` keyword but doesn't fully match the mnemonic-or-quoted-literal
grammar above (an unquoted code like `FILE-STATUS IS 92`, a mnemonic with
digits like `FILE-STATUS IS EOF10`, a missing value) raises `CutParseError`
at that line instead of silently falling through to `body_lines` and being
spliced verbatim into generated COBOL, where it would surface as a
confusing `cobc` compile error instead of a `.cut`-level refusal.

`FILE-STATUS IS` also parses correctly *inside* an open `MOCK READ ...
ROWS` body, not just in the ordinary mock-body case above — fixed
2026-08-10 (audit finding F19). `parser.py`'s `elif` chain used to check
`in_mock.rows is not None` (the generic ROWS-row branch) before the
FILE-STATUS IS / malformed-FILE-STATUS branches, so any `FILE-STATUS IS`
line written inside a `ROWS` body fell into "malformed ROWS row" instead
— reordered so the FILE-STATUS IS branches are checked first.

### `CONDITION IS <condition>` (MOCK CICS only, issue #268)

Inside a `MOCK CICS "..."` body without ROWS: the mocked command raises
that CICS condition (`NOTFND`, `DUPREC`, ...), stored on
`MockDirective.cics_condition`. The dispatch ends with `GO TO <label>` for
the `EXEC CICS HANDLE CONDITION` label in force at the matched command
(an IGNOREd condition does nothing; a condition with no entry falls to
`ERROR`'s label) -- see [splicer](splicer.md). Anywhere else, a duplicate,
or a malformed `CONDITION ...` line is a `CutParseError`. Lint refuses
`UNSUPPORTED_CICS_CONDITION` when no handler covers the condition (the
real command would abend), the command has RESP/NOHANDLE, or the program
uses PUSH/POP HANDLE.

### `CAPTURE ARG <n> INTO <target>`

Usable inside a `MOCK CALL "..."` / `MOCK MQ "..."` (category `CALL`) or
bare `MOCK CALL <identifier>` (category `DYNCALL`) body only — any other
category raises `CutParseError` at that line. `<n>` is a 1-based
positive integer selecting the real `CALL`'s Nth `USING` parameter
*positionally* — deliberately not by COBOL variable name, so one
`CAPTURE` line stays correct even when two physical call sites sharing
the mocked key use differently-named arguments. `<target>` reuses
`_SUBSCRIPTED_NAME` (same fragment as `MOVE`'s target and `EXPECT`'s
data-name).

```
MOCK CALL "DISCRATE"
    CAPTURE ARG 1 INTO WS-CAPTURED-RATE
    MOVE 0 TO RETURN-CODE
END-MOCK
...
PERFORM CALC-DISCOUNT
EXPECT WS-CAPTURED-RATE TO BE 0.15
```

At splice time (`injector.build_site_dispatch`, see
[splicer](splicer.md)), `<n>` is resolved against *that exact physical
call site's* `CallStatement.using_parameters` and emitted as `MOVE
<real-arg-name> TO <target>`, before the directive's own body lines —
the captured value is then asserted with the ordinary `EXPECT`, no new
assertion syntax. Multiple `CAPTURE` lines in one body are allowed (one
per `USING` argument worth capturing); the same `<n>` twice in one body
is a `CutParseError`. `<n>` of `0` or non-numeric is a `CutParseError`.

**Multi-call semantics: last call wins.** The `MOVE` re-fires on every
dispatch through that site's `WHEN` branch, identical to any
hand-written mock-body `MOVE` — if the mocked `CALL` is reached more than
once in one `TESTCASE` (e.g. inside a loop), the captured field holds
whichever call happened *last* by the time `EXPECT` runs. Per-call
history/table capture is not supported.

**Fail-closed validation:** `CAPTURE_ARG_OUT_OF_RANGE` (see
[analysis](analysis.md)) refuses if `<n>` exceeds the real `USING`
parameter count of any call site the directive matches **anywhere in the
program** — reachability is deliberately not a filter, because the splicer
isn't one either. Because dispatch is per physical *site*, not per key,
two sites sharing one mocked key can legitimately declare a different
number of `USING` parameters — this refuses if **any** matching site has
too few, even if another matching site would be fine (fail closed over
partial safety, same posture as `UNRESOLVED_FILE_STATUS_TARGET`).

**Synthesized targets (`UT-CAP-...`, 2026-09-04).** A `<target>` whose
name starts with `splicer.captures.CAPTURE_TARGET_PREFIX` (`UT-CAP-`) means
"declare this for me": `splicer.captures.plan_captures` synthesizes a
WORKING-STORAGE item mirroring the captured argument's own PICTURE/USAGE
(a DISPLAY-only group becomes one `PIC X(<byte length>)` field, which is
exactly what a group MOVE copies) and a reset line, both threaded through
`cli.checks.extra_working_storage` / `extra_reset_lines_for` so all four
splice-and-compile pipelines (`run`, `debug`, `export`, `mutate`) stay in
step. The reset matters as much as the declaration: the suite compiles to
ONE binary, so an unreset capture would let a case that never reached its
CALL assert against the previous case's value.

That is what finally let `generate` scaffold captures at all — the target
previously had to be an existing item of a compatible type, so finding or
adding one was a manual step before every single capture, and the scaffold
never emitted one. The reserved prefix is what keeps it from being a
footgun: a mistyped real data name never starts with `UT-CAP-`, so it can
never silently become a new field. Fail-closed on everything else:
`UNRESOLVED_CAPTURE_TARGET` (raised from `run_static_checks` step 9)
refuses a synthesized target whose argument names different items of
different layouts at different matching call sites (items that all mirror
to the same declaration, such as an IMS program's `DLI-GU` and `DLI-ISRT`,
both `PIC X(4)`, share one field), whose layout cannot be mirrored (a table, a
PICTURE-less COMP-1/POINTER item, a group holding non-DISPLAY data whose
bytes an alphanumeric copy would render unreadable), or whose name the
program already declares. A target WITHOUT the prefix is untouched — it
still has to exist in the program, exactly as before.

`generate` emits a `CAPTURE ARG <n> INTO UT-CAP-<key>-<n>` per mirrorable
argument (`_capture_lines_by_key`, precomputed onto `ProgramContext`),
first in the mock body so the `.cut` reads the way it executes, plus one
`*> STUB EXPECT <target>` comment per capture after the `PERFORM` — a
captured value with nothing pointing at it is not an assertion, and `run
--record-expectations` promotes those stubs to real `EXPECT` lines from an
actual run, which is the workflow that makes a captured argument useful
without the author guessing the value up front. The generator applies the
same mirrorability and agreement checks the refusal does, so a scaffolded
`.cut` never trips its own gate: an argument that fails either is simply
not captured, and the boundary's other arguments still are.
Agreement means every CALL site sharing the key passes the SAME item at
that position (and every site passes that many arguments at all); a key
called from several places whose sites agree is captured like a
single-site one (before 2026-09-27 any key with 2+ sites got no captures).
Arguments are resolved with the splicer's own `captures._site_argument`
over the normalized lines, so a quoted literal is never captured (its
value is fixed by the source) -- comparing bare names instead scaffolded a
capture of `"ABC"` whenever an item ABC existed, and a refused one when one
site passed the literal and another the item (fixed 2026-09-28, round 6).
From cobol-parser 3.1 a quoted literal operand keeps its quotes in
`using_parameters` (`'D''E'` reports as `"D'E"`); `injector.reported_literal`
recognizes that spelling, the text re-scan accepts either one, and the
text's own token is still the one moved. Under cobol-parser 1.8.x a CALL with a numeric literal operand loses it
from `using_parameters`, the text re-scan then trusts nothing, and a quoted
literal on that CALL still reads as a data-name -- consistently in both
the generator and the splicer, so no refusal.

See docs/2026-08-11-argument-capture-design.md for the full design and
rejected alternatives (a dedicated `VERIFY ... WAS CALLED WITH ARG n =
value` combined syntax; capturing by COBOL variable name instead of
position; per-call history capture). That doc lists `generate` emitting
`CAPTURE` automatically as explicitly out of scope for v1; this is the
follow-up that closed it.

## Case rules

Every DSL keyword is case-sensitive uppercase (`testsuite "x"` is an
`unrecognized statement` error) with one deliberate exception: **`END-MOCK`
is case-insensitive and accepts an optional trailing period** (`END-MOCK.`,
`end-mock` — the trailing period is the natural COBOL habit). The leniency
exists because a missed END-MOCK doesn't fail at its own line; it silently
swallows the rest of the file into the mock body. Bare keys are upper-cased
by the parser; quoted keys are preserved exactly (see below). Names are not
keywords: like cobc, a `PERFORM` target and its `THRU` end may be written in
any case (`PERFORM read-one` finds `READ-ONE`, #164).

### Statement order inside a TESTCASE (2026-10-05, #150)

Setup `MOVE`s always run before the `PERFORM` and `EXPECT`/`VERIFY` always
after the last one, whatever their position in the file. So the parser
refuses the orders that would mean something else: an `EXPECT`/`VERIFY`
above the first `PERFORM` (`EXPECT before the PERFORM`), a `MOVE` or
`PERFORM` below an assertion, and a `MOVE` after the last `PERFORM`
(`MOVE after the last PERFORM`). A `MOVE` between two `PERFORM`s sets up
the second call (multi-call case, see above). `MOCK` directives may sit anywhere. Data names containing a
`.` (`IN-REC.CUST-ID`) are refused too (#144) -- COBOL qualifies with
`CUST-ID OF IN-REC`, which the refusal now suggests (#252).

## `PROVIDER` parameterized test cases

`PROVIDER <name>` is a suite-level block (sibling of `TESTCASE`, must be
declared before any `TESTCASE` that references it) holding a `HEADER`
(bare, comma-separated column names) and one or more `ROW`s
(comma-separated, quote-aware-split free-form COBOL value text, same
convention as `MOVE`/`EXPECT` values). `TESTCASE "..." USING PROVIDER
<name>` binds a test-case template to it.

A `PROVIDER` block admits only `HEADER`/`ROW` lines (plus blanks/`*>`
comments) and is closed only by the next `TESTCASE` or `PROVIDER` line;
any other statement while it's open -- `MOVE`, `PERFORM`, `EXPECT`,
`VERIFY`, `MOCK`, `BEFORE-ALL`/`BEFORE-EACH` -- raises `CutParseError`
fail-closed. This is deliberate: opening a `PROVIDER` also clears the
current `TESTCASE`/`BEFORE-*` state (`case = None`, `mock_target =
None`), so before this rule existed a stray statement between/after
`ROW` lines silently attached to whichever `TESTCASE`/`BEFORE-*` block
was open *before* the `PROVIDER`, with any `{Placeholder}` left
unsubstituted (see `tests/unit/test_dsl_parser.py::
test_stray_move_inside_open_provider_raises` and the two neighboring
tests, including one that pins a `BEFORE-EACH` appearing while a
`PROVIDER` is open as an error too).

`parser.py`'s `_expand_providers` runs as the last step of `parse_cut()`:
it replaces a provider-bound `TESTCASE` with one ordinary `MockTestCase`
per row, substituting `{ColumnName}` tokens (`_PLACEHOLDER_RE`) into that
case's `MOVE` and `EXPECT` values only -- `MOCK` bodies, `MOVE` targets,
`EXPECT` data-names, `PERFORM` target/thru, and `VERIFY` stay untouched
and identical across every row. A token outside a literal (`MOVE {State}`)
gets the raw row text, quotes and all; a token inside a quoted literal
(`MOVE "{State}"`, `TO BE "State: {Name}"`, `_quoted_spans`) gets the row
value's content -- a quoted row's quotes dropped and its doubled quotes
undone (`_literal_content`), the template literal's own quote doubled --
so `ROW "NY"` and `ROW NY` give the same literal and `ROW "O'Hare, IL"`
can sit inside `"..."` (issue #376; a quoted placeholder with a quoted row
used to become `""NY""`, which lint passed and cobc rejected). A `{Column}` token naming one of the
bound provider's own columns inside a `MOCK` body is a `CutParseError`
at that line (`_reject_mock_body_placeholder`; `*>` comment lines are
exempt) -- left verbatim it linted clean and failed cobc on
`invalid symbol '{'`. The same token in a NAME position -- `MOVE` target,
`EXPECT` data-name, `PERFORM` target/THRU -- is likewise a `CutParseError`
(`_reject_name_placeholder`, 2026-09-28; the EXPECT form made cobc abort
with "Please report this!"). A token naming any PROVIDER's column in a
hook step (`MOVE` in BEFORE-/AFTER-EACH/-ALL) or a hook `MOCK` body is a
`CutParseError` at that line too (`_reject_hook_placeholders`, issue
#227): a hook belongs to no single row, and the token reached cobc
verbatim; checked after the whole file is read, since a PROVIDER may be
declared after the hook block. An unknown `{Foo}` token is a
`CutParseError` naming the provider's real columns; an undeclared/
mistyped `USING PROVIDER` reference errors at the `TESTCASE` line.

Generated cases are named `"<name> [row <n>: <first column value>]"` and
their `.line` points at that row's own `ROW` line (not the shared
`TESTCASE` header) -- `MockTestSuite.test_cases` after `parse_cut()`
returns holds only these expanded, ordinary cases: analysis, splicer,
runtime, report, and every CLI flag never learn `PROVIDER` existed. A
`TESTCASE` with no `USING PROVIDER` is never scanned for `{...}` tokens
at all -- strict backward compatibility.

See `docs/2026-07-20-provider-parameterized-test-cases-design.md` for
the full design and rejected alternatives (a single compiled
`OCCURS`-table loop, `ROW ( FIELD = value, ... )` pairs, `MOCK`-body
templating).

## `MOCK <kind> <key>` forms

Two key syntaxes, split by category:

| Syntax | Categories | Key regex | Example |
|---|---|---|---|
| Quoted | `CALL`, `MQ` (sugar), `SQL`, `CICS`, `DLI` | `"[^"]*"` | `MOCK CALL "DISCRATE"`, `MOCK SQL "UPDATE INVENTORY"` |
| Bare COBOL word | `CALL` (dynamic form), `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `START`, `UNLOCK`, `SORT`, `MERGE`, `RELEASE`, `RETURN`, `INITIATE`, `GENERATE`, `TERMINATE`, `ACCEPT`, `PARAGRAPH`, `SECTION` | `[A-Za-z0-9][A-Za-z0-9-]*` | `MOCK OPEN INV-FILE`, `MOCK CALL WS-PGM-NAME`, `MOCK SORT SORT-FILE`, `MOCK RETURN SORT-FILE ROWS ... TERMINAL (...)`, `MOCK PARAGRAPH CALC-TOTALS` |

Bare keys are upper-cased by the parser (`m.group("key").upper()`); quoted
keys are kept exactly as written.

`MockCategory` (in `model.py`) has 23 members. `MOCK`/`VERIFY` text spells
23 distinct keywords too (`sorted(set(m.keyword for m in MockCategory) |
{"MQ"})`), but the two counts don't line up member-for-member: `DYNCALL`
collapses into the `CALL` keyword (no `.cut` file is ever written with
`DYNCALL`), while `MQ` is a keyword with no member of its own (pure sugar
for `CALL`) — see `_resolve_category` in `parser.py`:

| Category enum | `.cut` keyword | How it's reached |
|---|---|---|
| `CALL` | `CALL` | `MOCK CALL "X"` (quoted key) |
| `DYNCALL` | `CALL` | `MOCK CALL WS-PGM` (bare key) — **never written as `DYNCALL`** in `.cut` files |
| `SQL`, `CICS`, `DLI` | `SQL`, `CICS`, `DLI` | quoted key, prefix-matches normalized EXEC text |
| `OPEN`,`CLOSE`,`READ`,`WRITE`,`REWRITE`,`DELETE`,`START`,`UNLOCK` | same | bare key = file/record name |
| `SORT`, `MERGE` | same | bare key = the SORT/MERGE statement's own SD file name -- only a plain-file-form site (`USING ... GIVING ...`, no INPUT/OUTPUT PROCEDURE) is ever classified into these categories; a mixed-form site (a USING/GIVING file paired with a procedure clause on the other side) stays `category=None`/`UNSUPPORTED_SORT_MERGE`, see [analysis](analysis.md) |
| `RELEASE`, `RETURN` | same | RELEASE keys on the record name (WRITE-shaped); RETURN keys on the SD file name (READ-shaped, `ROWS ( ... ) TERMINAL ( ... )` sugar reused from READ -- see below -- but RETURN always needs its own `TERMINAL` group since it is never in `FILE_STATUS_CATEGORIES`). Both only ever appear inside a SORT's INPUT/OUTPUT PROCEDURE, but are mockable independent of whether the enclosing SORT/MERGE turned out pure-procedure (left real) or mixed-form (still refused) |
| `ACCEPT` | `ACCEPT` | bare key = data-name being accepted into |
| `INITIATE`, `GENERATE`, `TERMINATE` | same | Report Writer (2026-09-02). Bare key = the report name (INITIATE/TERMINATE; a statement naming several reports is one site with several keys, like a multi-file OPEN) or the report/detail-group name (GENERATE). Grouped as `REPORT_WRITER_CATEGORIES` in `model.py`: bare-word keys, free-form body, no ROWS/TERMINAL/FILE-STATUS sugar (an RD has no status field) -- the splice alone is the mock, the RD/FD stay declared and the report file is never touched. Needs a cobol-parser that parses the REPORT SECTION (the 2026-09-02 release); earlier releases warn on it and the whole program refuses PARSE_WARNING before any directive is considered |
| `PARAGRAPH`, `SECTION` | same | bare key = a PROCEDURE DIVISION paragraph/section name — flow-target mocks, not boundaries; grouped as `FLOW_CATEGORIES` in `model.py` (see [analysis](analysis.md)'s `flow_mocks.py` and [splicer](splicer.md)'s header dispatch) |
| `CALL` (again) | `MQ` | `MOCK MQ "X"` — pure sugar, becomes a `CALL` directive; MQ is invoked through static `CALL`s, so there is no `MockCategory.MQ` |

`VERIFY` mirrors the same two-syntax split (`_VERIFY_QUOTED_RE` /
`_VERIFY_BARE_RE`), plus one more back-compat wrinkle: a bare `VERIFY "X" WAS
CALLED ...` with **no category keyword at all** resolves to `CALL` (v1
grammar had no category concept). `CALLED` and `PERFORMED` are accepted
interchangeably everywhere.

Why `DYNCALL` exists as a distinct enum member instead of overloading `CALL`
with a "is_dynamic" flag: it keeps every `(category, key)`-keyed structure
(tally registry, declared-`VERIFY` set, dedup sets) from ever cross-matching
a quoted static-CALL directive against a bare dynamic-CALL site, or vice
versa — see the docstring on `MockCategory` in `model.py` for the full
rationale.

### `MOCK READ <file> NEXT | PREVIOUS | KEY [<key>]` (2026-11-02)

A file read several ways (a VSAM KSDS read by key, browsed with READ NEXT
and READ PREVIOUS, or read by an alternate key) can be mocked per access
form: `MOCK READ CUST-KSDS NEXT`, `MOCK READ CUST-KSDS PREVIOUS`, `MOCK READ
CUST-KSDS KEY` (a keyed READ by the prime key) or `MOCK READ CUST-KSDS KEY
CU-NAME` (by that alternate key). `VERIFY READ <file> <form> WAS CALLED`
counts one form. Only `READ` takes a form; any other category raises
`CutParseError`. The form is kept in the directive's key (`"CUST-KSDS
NEXT"`); `MockDirective.file_key` is the bare file name, used for FILE
STATUS lookups. `mock_surface.read_form_of` classifies each READ site
(`BoundarySite.read_form`, from the SELECT's organization and access mode
in `MockSurface.file_selects`), and `refusal.matching_directives` picks the
most specific directive that matches a site (`_match_specificity`), so a
plain `MOCK READ CUST-KSDS` still answers every form no qualified directive
claims. `generate` qualifies a file's READ mocks only when its sites read
it in more than one form (`split_read_files`); a keyed READ's rows drop the
key field the program sets itself, and a status a form cannot return is
replaced with `00`. A failed READ with a status other than `0x` is
status-only (no record); `02`/`04` come with the record. The generator's
call counts follow the same rule (`_sites_for_key(..., among=)`,
`_most_specific`): a `READ F KEY IS ALT` site is counted under `READ F KEY
ALT` only, not also under `READ F KEY`, so a generated `VERIFY` matches the
tally the run keeps (#402).

### `MOCK OPEN <file> INPUT | OUTPUT | I-O | EXTEND` (2026-11-02)

The same idea for OPEN: `MOCK OPEN AUD-ESDS EXTEND` answers only the OPENs
of that file in that mode (`BoundarySite.open_modes`, per file, so each
file of `OPEN INPUT A OUTPUT B` has its own), and `VERIFY OPEN <file>
<mode>` counts them. Only `OPEN` takes a mode. A bare `MOCK OPEN <file>`
answers every mode no qualified directive claims; on a multi-file OPEN the
most specific directive is picked per file. `generate` qualifies a file's
OPEN mocks when single-file OPENs open it in more than one mode
(`split_open_files`, `_with_open_modes`), so a case can fail the OPEN
EXTEND that finds a log missing (35) while the OPEN OUTPUT that creates it
succeeds; before, the one `MOCK OPEN` gave 35 to all of them. On a
multi-file OPEN mocked by one directive, a failure of a file other than
the directive's own is a `MOVE "<code>" TO <its status field>` in the body
(`_merged_status_only_body`); `FILE-STATUS IS` set the directive's file.

## `USE REAL CALL "X" FROM "<path>"` (2026-11-01)

Allowed wherever a `MOCK` is (TESTCASE, BEFORE-EACH, BEFORE-ALL). The parser
(`_USE_REAL_RE`) builds an ordinary CALL `MockDirective` with
`real_source` (the path as written, relative to the `.cut`) and
`real_line`; `MockDirective.is_real` tells it apart and `describe()` reads
`REAL CALL "X"`. Because it is a directive, BEFORE-* precedence and the
duplicate-MOCK rule apply unchanged. Static CALL by literal only; a
malformed line fails with "malformed USE REAL directive". What it does
downstream: [docs/2026-11-01-real-call-integration-design.md](../docs/2026-11-01-real-call-integration-design.md).

## `*> STUB EXPECT` comments (`mockymock run --record-expectations`)

```
*> STUB EXPECT <data-name> [-- <note>]
```

A convention, **not a grammar addition** — as far as `parse_cut()` is
concerned this is an ordinary `*>` comment (parses today with zero parser
changes) that does nothing at runtime until `mockymock run
--record-expectations` fills it in, turning it into a real
`EXPECT <data-name> TO BE <value>` line in place. `<data-name>` reuses the
same `_SUBSCRIPTED_NAME` fragment `EXPECT`/`MOVE` targets already parse
with, so a subscripted stub (`WS-TABLE(1, 1)`) is recognized identically.
`-- <note>` is optional, free text, never parsed for meaning (mirrors
cobol-parser's `Expectation.note` field it's meant to echo, e.g.
`"computed in CALC-TOTALS"`).

Meant to be written next to a would-be `EXPECT` — inside a `TESTCASE`, at
the point a real assertion would go — for a field whose correct value the
author (or an automated scaffolder, see cobol-parser's tier-3 stub
`Expectation`s) doesn't yet know. `mockymock.analysis.stub_expectations`
scans for these as raw text (deliberately not part of this grammar — see
that module's docstring for why); `mockymock.report.record_rewrite`
matches a scan against a recorded run and does the rewrite. Once
recorded, the resulting `EXPECT` line is an ordinary one in every way —
nothing distinguishes it from a hand-written `EXPECT`, and nothing about
this feature can ever touch it again (there's no more `*> STUB EXPECT`
text left to match). See
docs/2026-08-04-record-expectations-design.md for the full design.

A stub on an item the program fills from the system clock (`record_rewrite.clock_value_fields`: the target of `ACCEPT x FROM DATE/TIME/DAY/DAY-OF-WEEK` or `MOVE FUNCTION CURRENT-DATE TO x`, direct targets only) is **skipped, with the reason**, unless its case pins the clock with `MOCK ACCEPT x` (#240): today's value recorded as a golden fails on a later run.

# AST Model (`model.py`)

| Class | Fields | Notes |
|---|---|---|
| `MockCategory` (Enum) | `CALL, DYNCALL, OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, UNLOCK, SQL, CICS, DLI, ACCEPT, PARAGRAPH, SECTION` | `.keyword` property maps `DYNCALL → "CALL"`, everything else to its own name |
| `MockDirective` | `category, key, body_lines: list[str], rows: list[list[tuple[str, str]]] \| None, terminal_row: list[tuple[str, str]] \| None, captures: list[tuple[int, str]]` | `.program_name` is v1-compat alias for `.key` (CALL-only meaning); `.describe()` renders `.cut`-style text (`CALL "X"`, `CALL WS-PGM`, `READ INFILE`) used in refusal messages; `rows` is set only for a `MOCK SQL "..." ROWS`, `MOCK READ <file> ROWS`, or `MOCK RETURN <sd-file> ROWS` directive and is mutually exclusive with `body_lines`; `terminal_row` holds a READ/RETURN ROWS directive's optional (READ) or effectively mandatory (RETURN) `TERMINAL ( FIELD = value, ... )` group (its rows-exhausted `WHEN OTHER` field assignments) — always `None` for SQL rows (SQLCODE 100 is fixed) and for non-ROWS mocks; `captures` holds `CAPTURE ARG <n> INTO <target>` `(n, target)` pairs, only ever non-empty for CALL/DYNCALL directives |
| `DataProvider` | `name, line, header: list[str], rows: list[list[str]], row_lines: list[int]` | Parser-internal only -- never stored on `MockTestSuite`/`MockTestCase`; consumed and discarded by `_expand_providers` before `parse_cut()` returns |
| `ExpectDirective` | `data_name, expected_value, operator` | one `EXPECT` line; `operator` is the canonical relation asserted between the two (one of `EXPECT_OPERATORS`, default `"="`) |
| `VerifyDirective` | `category, key, expectation` | `.program_name` same v1-compat alias as `MockDirective` |
| `MockTestCase` | `name, mocks, setup_moves: list[(value,target)], perform_target, perform_thru: str\|None, expectations, verifications, template_name: str\|None` | `perform_thru` is `None` unless `PERFORM X THRU Y` was used; `template_name` is the provider-bound TESTCASE's own name on each expanded row (`_instantiate_row`), `None` otherwise -- `report` keys a row's labelled assertions by it (#328) |
| `MockTestSuite` | `name, test_cases` | `all_mock_keys()` returns every distinct `(category, key)` pair across all test cases, **first-appearance order** — this ordering is load-bearing: the tally registry, driver bookkeeping, and the splice loop all iterate this list, so first-appearance order determines codegen order |

`FILE_OP_CATEGORIES` (frozenset of the 8 file-op categories) and
`EXEC_CATEGORIES` (frozenset of `SQL/CICS/DLI`) are module-level constants
used both here and by `generator.py` to branch on key-syntax family.

# Parser (`parser.py`)

Single-pass line scanner over `_lines.split_cut_lines(text)`, tracking three
pieces of mutable state: current `suite`, current `case`, and current open
`in_mock` directive (`None` when not inside a `MOCK...END-MOCK` block).

**Line splitting and blanks (2026-11-05 bug hunt):** `.cut` text is split on
`\n` / `\r\n` / `\r` only (`split_cut_lines`), never `str.splitlines()`,
which also broke a line at a form feed, VT, NEL or U+2028: a page eject in a
`*>` comment made the comment's tail an "unrecognized statement" and shifted
every later line number. Every `.cut` reader that numbers lines uses it --
the parser, `cli/checks.py`, `cli/discovery.read_program_line`,
`analysis/stub_expectations`, `analysis/assertion_labels` and
`report/record_rewrite` -- so lint, stub scanning and the
`--record-expectations` rewrite agree. Each line then goes through
`_plain_blanks`: any whitespace other than space/tab outside a quoted literal
(a pasted no-break space) becomes a space, because a MOCK body line is spliced
verbatim and cobc read `MOVE<NBSP>7` as one word.

Key regexes, matched in this order per non-blank line:

1. If inside a `MOCK` body: look only for `END-MOCK` (any case, optional
   trailing period); anything else is appended verbatim to `body_lines`
   (no further parsing — a mock body's contents are opaque to the DSL
   parser), with one fail-closed exception: a line holding a COBOL
   sentence-terminating period (`.` followed by whitespace/end of line,
   outside quotes and before any `*>`) raises `CutParseError`
   (`_reject_body_sentence_period`, 2026-09-27). The body is spliced into
   a `WHEN` of the generated `EVALUATE UT-CURRENT-CASE`, where the period
   ends the sentence mid-EVALUATE -- `lint` used to pass and `cobc` then
   failed on generated code (`unexpected END-EVALUATE`). ROWS/`TERMINAL`
   field values get the same check. A decimal point (`1.5`), a period
   inside a literal, or one in a comment is untouched. A second exception
   (issue #287, `_reject_body_control_flow`): a body line that leaves the
   body -- `PERFORM <paragraph>` (THRU/TIMES/UNTIL forms included), `GO
   TO`, `GOBACK`, `STOP RUN`, `EXIT PROGRAM`, outside literals and `*>`
   comments -- raises `CutParseError` at its line. Nothing walks a mock
   body, so a performed paragraph's CALLs/file I/O ran for real after a
   clean lint, and a terminator ended the whole binary (CRASH, every later
   case NOT RUN). Inline `PERFORM VARYING/UNTIL/WITH TEST/n TIMES/<id> TIMES
   ... END-PERFORM` is allowed. The error is held until the block's
   END-MOCK, so a MOCK missing its END-MOCK (which swallows the case's own
   PERFORM) still reports "unterminated MOCK". Following such edges instead
   (pushing the targets into the case's reachable set) is not implemented.
2. `*>` comment (only reachable when not inside a mock body). A
   *trailing* `*>` comment (outside quotes) is stripped from every line the
   DSL parses itself before matching -- outside MOCK blocks, and inside one
   for ROWS rows, `TERMINAL`, `CAPTURE`, `FILE-STATUS` and `END-MOCK`
   (`_strip_inline_comment`, issue #236: it used to be swallowed into an
   EXPECT value or a PROVIDER ROW column and spliced into the driver).
   Plain MOCK body lines keep theirs; cobc reads it there. A MOVE/EXPECT
   value, ROWS/`TERMINAL` value or PROVIDER `ROW` value whose quoted
   literal never closes raises `CutParseError` at its line
   (`_reject_unterminated_literal`, issue #270).
3. `TESTSUITE "..."` — errors if a suite is already open (one per file).
4. `TESTCASE "..."` — requires `suite` already set; resets the per-case
   duplicate-MOCK tracker. An empty or blank name raises `CutParseError`
   (issue #308: the driver's `START:` marker would carry no name, and
   `--case` could not select it); `report.results`' `_CASE_START_RE`
   accepts an empty name anyway, so a printed START is never dropped.
5. `MOCK <quoted-cat> "<key>"` then `MOCK <bare-cat> <key>` — requires
   `case` already set; whichever matches opens `in_mock` and appends it to
   `case.mocks` immediately (body lines get attached as they arrive on
   subsequent iterations, single object mutated in place). An empty quoted
   key (`MOCK CALL ""`) and a duplicate `(category, key)` within the same
   TESTCASE both raise `CutParseError` here (the duplicate error names both
   line numbers; it used to surface much later as an `AMBIGUOUS_MOCK`
   refusal with misleading advice).
6. A line starting with literal `MOCK` that matched neither pattern raises
   `CutParseError` with a message that spells out the two key-syntax
   families — this is the fail-closed path for typos like `MOCK CALL
   DISCRATE` (missing quotes) or an unknown category word.
7. `MOVE <value> TO <target>` — appended to `setup_moves` as a tuple, in
   file order (order matters: later `MOVE`s to the same target win at
   runtime, same as COBOL).
8. `PERFORM <target> [THRU|THROUGH <thru>]` — a second PERFORM in the
   same TESTCASE moves the first one and its MOVEs to `case.steps`.
9. `EXPECT <name> TO BE <value>`.
10. `VERIFY` quoted then bare (mirrors step 5's two-family split, plus the
    no-category-means-CALL back-compat case). The expectation phrase is
    validated here via `_validate_expectation`.
11. Anything else: `CutParseError: unrecognized statement`.

After the full scan, two more checks raise `CutParseError`: `suite is None`
(no `TESTSUITE` line ever matched), and `in_mock is not None` — an
unterminated `MOCK` body errors with the line number of the `MOCK` line
that opened it (`tests/unit/test_dsl_parser.py` pins both).

# Generator (`generator.py`)

`scaffold_cut(suite_name, surface: MockSurface) -> str` builds starter `.cut`
text from static analysis, not from existing `.cut` files (no round-trip
model → text serializer exists elsewhere in this package — `scaffold_cut` is
the only text producer, and it emits strings directly rather than
constructing `MockTestSuite`/`MockDirective` objects and rendering those).

Rules:

- Groups `surface.boundary_sites` by `paragraph_name`; one `TESTCASE` per
  paragraph that has at least one **usable** site. A site is unusable and
  skipped if `site.category is None`, or if it's `nested` but has no
  validated splice `span` (unspliceable nested sites are surfaced elsewhere,
  via the CLI's unsupported-boundaries listing, not here).
- Each generated `TESTCASE` mocks **all** of that paragraph's own mockable
  sites, deduped by `(category, key)` — deliberately not a partial subset,
  because a partial mock would walk the user straight into the run
  command's refusal gate (`UNMOCKED_*` checks: an unmocked CALL has nowhere
  to link, unmocked file I/O hits a nonexistent sandbox file, unmocked EXEC
  can't compile, unmocked `ACCEPT` reads real stdin).
- Only covers each paragraph's **own** sites — boundaries reached
  transitively via `PERFORM` are not auto-mocked; those still need manual
  `.cut` edits (the run command's refusal gate names them precisely when
  missing).
- Whole main line (2026-11-02, `ProgramContext.main_line_thru`): a
  scenario whose entry is the program's first paragraph is generated as
  `PERFORM <first> THRU <last paragraph>` when the program carries on past
  that paragraph (its last statement is no STOP RUN/GOBACK/EXIT PROGRAM)
  and `find_terminator_plans` refuses none of the terminators that range
  reaches (they end the case at `UT-PROGRAM-END`, see [splicer](splicer.md)).
  Mocks are computed from the whole range. NIST CCVS85's `OPEN-FILES`
  GO TOs on to the tests, so its cases used to test that paragraph alone.
  A program that also PERFORMs its terminator's paragraph keeps the bare
  PERFORM. So does a suite `lint` refuses more cases of than of the same
  scenarios with a bare PERFORM (`cli.main._main_line_or_bare`, a note on
  stderr): the longer range can reach statements no MOCK replaces (NIST
  IX217A's WRITE ... INVALID KEY with no END-WRITE). Identical check lines
  in a case are written once.
- Exact counts (`analysis.exact_counts`): a site after a branch holding a GO
  TO (`READ F AT END GO TO P-END`) gets no exact VERIFY count, like one
  after a branch holding a STOP RUN (NIST RW301M).
- `--per-paragraph` PERFORMs a paragraph `THRU` the exit the program
  itself names (`ProgramContext.thru_exit`: every `PERFORM X` in the
  program says `THRU` the same paragraph), and computes its mocks from that
  range. A bare `PERFORM X` let X's `GO TO X-EXIT` leave the PERFORM and
  fall through to the end of the program (INTCALC, 2026-10-24).
- Placeholder bodies (`_PLACEHOLDER_BODIES`): `CALL`/`DYNCALL` →
  `MOVE 0 TO RETURN-CODE`; `SQL` → `MOVE 0 TO SQLCODE`; file-op categories →
  empty body; `ACCEPT` → `INITIALIZE <target>` (built per-site, not from
  the static dict, since it needs the target name). `INITIALIZE`, not
  `MOVE SPACES` (issue #330): cobc rejects MOVE SPACES to a numeric or
  numeric-edited target, and this body is also lint's suggested fix and
  what `--fill` / `--per-paragraph` / `--placeholder` insert.
- Dynamic CALL targets (`_per_target_body`, 2026-10-29): a `MOCK CALL
  <identifier>` body, bundle-driven or placeholder, is wrapped in
  `EVALUATE <identifier>` with one `WHEN "<program>"` per program name
  `ProgramContext.dynamic_targets` knows for it (cobol-parser's
  `DynamicCallAnalyzer`: VALUE clauses and literal MOVEs; SPACES / LOW- /
  HIGH-VALUES / ZERO and all-digit values are dropped) and a `WHEN OTHER`,
  each holding the same body, so the unedited mock behaves exactly as before
  and a test edits one branch per callee. A comment above it lists the
  targets (`..., and values this analysis cannot follow` when
  `possible_values_incomplete`). One complete target, more than
  `_MAX_TARGET_BRANCHES` (5), or an identifier declared twice gets the
  comment only; no known target leaves the body untouched.
- Per-category directive-line shape (`_directive_for`):
  - `CALL`: `MOCK CALL "name"` normally, `MOCK MQ "name"` if `site.is_mq`;
    returns `None` (site skipped) if no key was captured — emitting
    `MOCK CALL ""` would no longer round-trip, since the parser rejects
    empty quoted keys.
  - `DYNCALL`: `MOCK CALL <identifier>` — bare, unquoted, from
    `site.keys[0]`.
  - File-op categories: `MOCK <CATEGORY> <key>`; returns `None` (site
    skipped) if the site parsed no usable key.
  - `ACCEPT`: `MOCK ACCEPT <target>`; returns `None` if no key.
  - `SQL`/`CICS`/`DLI`: key is **not** the full statement text — it's the
    shortest word-prefix of `site.match_text` that's unique among the
    program's sites of the same category (`_unique_prefix`), so the
    generator itself never emits an `AMBIGUOUS_MOCK` pair that the splicer
    would later reject. Falls back to the full text if no proper prefix is
    unique. When another site's whole text is a prefix of this one
    (`SYNCPOINT` / `SYNCPOINT ROLLBACK`, `RETURN` / `RETURN TRANSID(...)`),
    the shorter text is the key for both (issue #248): the fallback full
    text already matches the longer site, so a second key was
    `AMBIGUOUS_MOCK`. One directive answers both sites.
- **`directive_snippet(site, surface) -> str | None` (2026-09-15)** wraps
  `_directive_for` to render one site's full `MOCK ... END-MOCK` block as a
  single string (4-space header/footer, 8-space body — exactly what
  `_scaffold_placeholder` itself emits). `None` whenever `_directive_for`
  is. This is the one place `RefusalReason.suggested_fix`
  (`analysis/refusal/_gates.py`) and `generate --fill`
  (`cli/main.py`'s `_fill_cut_file`) both get their fix text from, so a
  refusal's suggestion and a fresh scaffold can never disagree about what
  a site's directive looks like. See
  docs/2026-09-15-actionable-refusals-and-fill-design.md.
- Output shape per paragraph:
  ```
  TESTCASE "<paragraph> boundaries: <label1>, <label2>"
      MOCK <cat> <key>
          <placeholder body lines, indented>
      END-MOCK
      ...
      PERFORM <paragraph>
  ```
  `labels` are deduped `site.label` values joined with `", "`, used only in
  the human-readable `TESTCASE` name.
- **Reached boundaries (2026-10-10).** A paragraph's case mocks every
  boundary its `PERFORM` can reach (`_reachable_sites`: its own sites, then
  those of every paragraph `ProgramContext.reachable_from` reaches, in
  source order), not just its own -- the same walk lint gates on. Before,
  a paragraph that PERFORMed another touching a boundary got a scaffold
  its own lint refused (UNMOCKED_*); across `examples/` and the enterprise
  corpus that took lint-clean plain scaffolds from 18 to 27 of 34. Falls
  back to the paragraph's own sites when reachability can't be
  established, as the bundle path's #143 filter does.
- Boundaries between `PROCEDURE DIVISION.` and the first paragraph header
  (cobolparser's unnamed `""` paragraph) are not scaffolded: no `PERFORM`
  can enter there, and emitting one produced a bare `PERFORM ` that made
  the whole generated file unparseable (fixed 2026-09-28, round 6). They
  are listed in a `*>` comment block under `TESTSUITE` instead.
- Suite and TESTCASE names pass through `_quote_safe` (double quotes
  become single quotes): the .cut grammar has no escape syntax for a `"`
  inside a quoted name, so interpolating one raw would make the scaffold
  unparseable.

### `ROWS` cursor sugar (`SQL`) and `ROWS ... TERMINAL` (`READ`, `RETURN`, `CALL`, `DLI`, `CICS`, `ACCEPT`)

`MOCK SQL "<prefix>" ROWS ( FIELD = value, ... ) ( FIELD = value, ... )
END-MOCK`, `MOCK READ <file> ROWS ( FIELD = value, ... ) ( ... )
[TERMINAL ( FIELD = value, ... )] END-MOCK`, and `MOCK RETURN <sd-file>
ROWS ( FIELD = value, ... ) ( ... ) TERMINAL ( FIELD = value, ... )
END-MOCK` were the first three categories `ROWS` was valid on (RETURN
joined 2026-08-17, SORT/MERGE mocking); `CALL` (quoted static key, and
`MOCK MQ`, which is CALL), `DYNCALL` (bare `MOCK CALL WS-PGM`) and `DLI`
joined 2026-10-05 -- see "Per-call sequencing" below -- and `CICS` joined
2026-10-13 (#169) on the same terms, for the STARTBR/READNEXT browse loop
whose end only a RESP set by `TERMINAL` can signal. The set is
`model.ROWS_CATEGORIES`; any other category raises `CutParseError` at
parse time (`"ROWS is only supported for MOCK SQL, MOCK READ, MOCK
RETURN, MOCK CALL (static or dynamic), MOCK MQ, MOCK DLI, and MOCK CICS,
not MOCK <cat>"`). All three store structured
rows on `MockDirective.rows` instead of free-form `body_lines` — the two
are mutually exclusive by construction (the parser routes lines to one or
the other based on whether `ROWS` appeared on the opening line). Row
values are unparsed free text (matching `EXPECT ... TO BE <value>`'s
convention) split on top-level commas — `_split_top_level` in `parser.py`
is quote-aware, so a value like `EMP-NAME = "SMITH, JR."` isn't cut at the
comma inside the literal. An empty `ROWS` block (`ROWS` immediately
followed by `END-MOCK`/`TERMINAL`) is a `CutParseError`, not a silent
no-op.

**`TERMINAL ( FIELD = value, ... )`** is READ/RETURN-only grammar
(`_TERMINAL_RE` in `parser.py`): an optional (for READ) or, in practice,
**mandatory** (for RETURN — see below) line inside a `MOCK READ ... ROWS`
or `MOCK RETURN ... ROWS` body, at most one per directive, giving the
rows-exhausted branch's own field assignments instead of the parser's
implicit default. Parsed only while `in_mock.rows is not None` (i.e. only
inside an open `ROWS` block); using it inside `MOCK SQL ... ROWS` is a
`CutParseError` (SQLCODE's exhaustion value is fixed at 100, not
overridable), as is a second `TERMINAL` group on the same directive
(`"duplicate TERMINAL group"`). Stored on `MockDirective.terminal_row`,
`None` when omitted. **RETURN has no implicit default at all** — it is
never in `FILE_STATUS_CATEGORIES` (a SORT/MERGE's SD has no FILE STATUS
clause of its own, same reasoning as WRITE/REWRITE, see
[analysis](analysis.md)) — so `refusal.check_test_case`'s
`UNRESOLVED_FILE_STATUS_TARGET` check refuses a `MOCK RETURN ... ROWS`
with no `TERMINAL` group whenever the RETURN has no liftable `AT END`
clause, not just when a status field happens to be missing (unlike READ,
where the same check only fires when BOTH the TERMINAL group and a FILE
STATUS field are absent). A RETURN or READ whose matched sites all have a
liftable `AT END` clause is accepted without either (issue #341):
exhausting the rows runs that clause, which ends the loop.

A keyed READ (a random READ of an indexed or relative file,
`BoundarySite.read_form` `KEY` / `KEY <alt>`) that runs out of rows finds
no record instead (2026-11-05): the implicit default is `MOVE "23"`, the
outcome field gets "23" too, so its INVALID KEY clause runs, and a keyed
READ whose sites all have a liftable INVALID KEY clause needs neither a
FILE STATUS field nor a TERMINAL group (`refusal._at_end_ends_rows`).
Before, it reported 10 like a sequential read, which runs neither INVALID
KEY nor NOT INVALID KEY.

A `PERFORM ... UNTIL <flag> = <value>` loop driven by the READ's own
`AT END`-set flag (rather than the file's `FILE STATUS` field) needs that
flag's own `MOVE` inside the `TERMINAL` group too: the splicer replaces the
whole READ statement, `AT END` clause included, so without an explicit
`MOVE <value> TO <flag>` in `TERMINAL` the loop-guard flag is never set and
the loop never stops — the implicit default (`MOVE "10" TO <status field>`
when omitted) only satisfies a FILE-STATUS-driven loop, not a flag-driven
one.

**Per-call sequencing: `MOCK CALL "X" ROWS ( ... ) TERMINAL ( ... )`
(2026-10-05).** A plain `MOCK CALL` body answers every call of its key the
same way, which capped a whole-program case on any program that calls one
routine for several purposes in a loop (IMS `CBLTDLI` as priming GHN,
DLET and loop GHN; `MQGET`; a DB2 access module) at its empty-input path.
`ROWS` on `SEQUENCED_CALL_CATEGORIES` (`CALL`/`DYNCALL`/`DLI`/`CICS`,
and `ACCEPT` since #263, in `model.py`) gives one row per call, in order: row N fires when the key's
own tally reaches N. That tally is per `(category, key)`, so it counts
calls across **every** site the key matches (a DLI tally is per quoted
prefix key, since that is the directive's key), and `driver.py` zeroes it
at the start of each case, so every case restarts at row 1 (see the
hook rule below). These
categories have no implicit end-of-data value (no SQLCODE, no FILE
STATUS), so **`TERMINAL` is mandatory** -- the parser raises
`CutParseError` ("needs a TERMINAL ...") at `END-MOCK` when it is
missing, rather than splice a sequence whose last answer repeats forever
and hangs the loop until `run --timeout`. `TERMINAL` validity is
`model.TERMINAL_CATEGORIES` (READ/RETURN plus these three); SQL still
rejects it. `CAPTURE ARG` inside a `CALL ... ROWS` body is still parsed
(its branch precedes the row branch) and its MOVEs are emitted before the
rows block; "last call wins" still applies. Rows only `MOVE`; a response
needing `SET`/`IF` stays a plain body. Splice: `build_site_dispatch`'s
SEQUENCED branch calls `build_rows_block(tally, rows, row_suffix_moves=[],
exhausted_moves=<TERMINAL MOVEs>)`. Worked example:
`examples/real-world/ACCTPRG/ACCTPRG.cut`'s two "then stops at GB" cases;
tests: `tests/unit/test_call_sequencing.py`.

**A re-OPEN rewinds READ and FETCH rows (2026-11-05, round 2).** A `MOCK
READ <file> ROWS` and a `MOCK SQL "FETCH ..." ROWS` hand out row
`tally - rewind` (`TallyRegistry.row_cursor` / `rewind_name`, a `-REW`
twin of the tally, zeroed at each case start). Every OPEN site naming the
file, and every EXEC SQL OPEN of the cursor all of the FETCH key's sites
fetch from (`orchestrator._open_rewind_lines`, `_sql_cursor`), moves the
tally into it, so the rows start again at row 1 -- a real file is read
again from its first record after CLOSE and OPEN, and a cursor fetched
again from its first row. Before, the second pass got end of data at
once. VERIFY still counts every call (the tally never rewinds). BEFORE-ALL
hands a case its rows counted from its own last OPEN (`-START` minus the
rewind). Behaviour change: a suite whose rows ran on across a re-OPEN
now sees them again.

**ROWS cursor across hooks (issue #223).** The tally is both the ROWS
cursor and the VERIFY count. A case's tally starts at 0 -- or, for a key it
inherits from BEFORE-ALL, at the count the BEFORE-ALL steps left
(`UT-...-START`, saved right after them) -- and is never zeroed again
inside the case: rows a priming READ/FETCH/CALL in BEFORE-EACH or
BEFORE-ALL consumed are not handed out again, exactly like a real file.
VERIFY counts only the case's own PERFORM through a per-key baseline
(`UT-...-BASE`), set equal to the tally at case start and again after the
BEFORE-EACH steps when they PERFORM; the generated check is
`IF (<tally> - <base>) NOT = n`. A case's own MOCK for the key replaces
the inherited one and starts its rows at 1.

**This grammar is hand-authoring only.** It exists for a human (or an
editor integration) writing a `.cut` file by hand against `mockymock
fixtures`' JSON output; `dsl/generator.py`'s bundle-driven scaffold
(`generate --with-data`/`--fixtures`, below) does **not** emit it — it
still hand-rolls its own `EVALUATE`/`WHEN <tally> = N` block for a
multi-row READ sequence (`_read_body`), mirroring this sugar's generated
shape rather than reusing the sugar's syntax. See
docs/2026-07-31-csv-sourced-rows-design.md, which proposed both this
inline form (now shipped) and a still-unimplemented `ROWS FROM CSV
"<path>"` row-source extension for `SQL` and `READ` alike.

Codegen happens at splice time (`injector.build_rows_block`), not parse
time, because the tally field name isn't resolved until
`naming.TallyRegistry` runs post-parse over the whole suite.
`build_rows_block(tally_name, rows, *, row_suffix_moves, exhausted_moves)`
is category-generic — it no longer hardcodes SQLCODE itself — each row
generates a `WHEN <tally> = N` branch that MOVEs its fields then appends
`row_suffix_moves` verbatim; `WHEN OTHER` (rows exhausted) appends
`exhausted_moves` verbatim. The two call sites in
`splicer/injector.build_site_dispatch` supply category-specific values:

- **SQL**: `row_prefix_moves=["MOVE 0 TO SQLCODE"]` (before the row's own
  MOVEs, so a row giving `SQLCODE = -305` keeps it -- as a suffix it was
  silently overwritten until 2026-10-13), `row_suffix_moves=[]`,
  `exhausted_moves=["MOVE 100 TO SQLCODE"]` (DB2's "not found" code) —
  fixed in v1.
  When the program names `SQLSTATE` anywhere (`orchestrator._SQLSTATE_RE`
  over the normalized lines, passed as `build_site_dispatch(sqlstate=True)`),
  the prefix also carries `MOVE "00000" TO SQLSTATE` and the exhaustion
  `MOVE "02000" TO SQLSTATE` (issue #313: a cursor loop ended by
  `UNTIL SQLSTATE = '02000'` never ended); a program that never names it
  gets neither, since its own SQLCA copy may not declare one. `generate
  --placeholder`'s SQL downgrade adds the same `"02000"`. `TERMINAL` is
  still not accepted on SQL ROWS.
- **READ**: `row_suffix_moves=[]` (a file-op category's implicit
  default-success `MOVE "00"` already precedes the whole dispatch block
  when the file declares a `FILE STATUS` field — see the `FILE-STATUS IS`
  section above — so there is nothing left to append per row).
  `exhausted_moves` is additive, not either/or (fixed post-PR #46 review,
  Task 3): when the file has a resolved `FILE STATUS` field it always
  starts with a default `MOVE "10" TO <status field>` (COBOL's real
  end-of-file status code), and the directive's own `TERMINAL` group's
  MOVEs (`[f"MOVE {value} TO {field}" for field, value in
  directive.terminal_row]`) — when present — are appended right after, so
  an author's own MOVE to that same field (if TERMINAL includes one)
  overrides the default by coming later in the same `WHEN OTHER` branch,
  and a TERMINAL group that never mentions the status field no longer
  leaves it stuck at whatever `"00"` the default-success MOVE set on the
  call that triggered `WHEN OTHER` — it gets the correct `"10"` instead.
  With no `FILE STATUS` field, `exhausted_moves` is just the TERMINAL
  group's own MOVEs. See [analysis](analysis.md)'s
  `UNRESOLVED_FILE_STATUS_TARGET` refusal for the case where **neither**
  exists and the READ has no liftable `AT END` clause either (with one,
  the exhausted branch moves `"10"` to `UT-MOCK-STATUS` and the lifted
  clause signals end-of-data, issue #341) — `check_test_case` refuses fail-closed before splicing is ever
  reached, so `build_site_dispatch` raising `ValueError` for that same
  gap is a should-be-unreachable production invariant, not a normal
  control path.

### Bundle-driven scaffold (`generate --with-data`, Phase 8 of gen-fixtures)

`scaffold_cut(suite_name, surface, bundle=None)` — `bundle=None` is the
paragraph-grouped path described above, unchanged. A real
`dsl.fixture_bundle.FixtureBundle` (parsed from cobol-parser's
`ProgramFixtureGenerator` JSON, see `fixture_bundle.py` and cobol-parser's
`docs/fixture-bundle-schema.md`) switches to `_scaffold_with_bundle`:

- **One `TESTCASE` per `bundle.scenarios[]` entry**, not per paragraph,
  named from `scenario.name`, body `PERFORM <scenario.entry>`. A scenario
  whose case comes out identical to an earlier one once comments are set
  aside (`_case_identity`: same mocks, same PERFORM, same checks) is left
  out, and a `*> NOTE:` under `TESTSUITE` (also on stderr) says how many
  (2026-11-02). The bundle plans scenarios over the whole main-line run,
  which can carry on past the entry paragraph by falling through or `GO
  TO` (NIST's `OPEN-FILES ... GO TO CCVS1-EXIT`); a case PERFORMs the
  entry alone, so on NIST 72 of 112 green suites repeated one case up to
  83 times under branch names it never took.
- **A READ whose generated rows move nothing** (a keyed READ of a record
  holding only its key) gets no row `EVALUATE` at all, and an empty row
  gets `CONTINUE`: `WHEN tally = 1 ... WHEN tally = 10 END-EVALUATE` with
  no statement failed cobc 3.1 ("invalid expression", NIST IX301M).
- **The join**: `_mockymock_boundary_keys(surface)` (this program's own
  walk — note it iterates *every* entry of `site.keys`, not just
  `keys[0]`, so a multi-file `OPEN A OUTPUT B` widens to both `(OPEN, A)`
  and `(OPEN, B)` even though it is one physical `BoundarySite`) is
  compared against `_bundle_boundary_keys(bundle)` (every fixture's
  `(category, key)` plus every `call_count`/`stub`-kind expectation's
  `ref`, since an OUT-direction boundary — a WRITE, a SQL
  INSERT/UPDATE/DELETE — gets no fixture at all, only a stub expectation;
  skipping stub refs here would misreport every OUT-direction boundary as
  a mismatch). Disagreement is never silent: `_warn_on_key_mismatch`
  prints both one-sided sets to stderr. Two mockymock-only shapes are
  expected, not disagreements, and are left out of it: RELEASE / RETURN
  (#262, never in a bundle), and a CALL / DYNCALL whose every argument the
  program supplies (#300, `_program_supplied_call_keys`: cobol-parser's own
  `BoundaryInventoryAnalyzer`, each `call_args` direction OUT -- the
  bundle counts it but has nothing to generate for it). This exact comparison is pinned by
  `tests/unit/test_fixture_bundle_contract.py`, parametrized over the
  `examples/*/` corpus — a mismatch there must be root-caused (nested-site
  span annotation missing, a real cobol-parser gap, etc.), not silently
  accepted; see that file's module docstring for the one currently
  accepted exception (`custprog`'s DCLGEN `EXEC SQL INCLUDE`, a
  cobol-parser preprocessing gap, not a Phase 1-8 regression).
- **`_bundle_mock_directives`** groups a scenario's fixtures by *physical
  site* (`id(site)`, not by key) before emitting anything — the same
  multi-file OPEN/CLOSE shape that widens `.keys` in the join above means
  naively emitting one directive per key would declare two `MOCK OPEN`
  directives that both match the same physical site
  (`AMBIGUOUS_MOCK`). One representative key per physical site is chosen
  and its status data merged instead. The representative is
  `generator.file_op_key(site, surface)` -- the same choice the
  bundle-less scaffold, lint's `suggested_fix` and `--fill` make
  (`_directive_for`): a multi-file OPEN/CLOSE is keyed on a file that is
  also the *only* file of another site of the same verb, else on
  `keys[0]`. Keying `OPEN INPUT A B` on `A` left a later `OPEN OUTPUT B`
  needing `MOCK OPEN B`, which also matches the multi-file site, so the
  generated suite refused `AMBIGUOUS_MOCK` (issue #312). One `MOCK OPEN B`
  now covers both sites. Shapes where no single key covers every site
  (`OPEN A B` plus separate `OPEN A` and `OPEN B`) still need hand
  editing by adding one MOCK per file, which the splicer applies together since issue #348. It returns `(lines, declared_keys,
  call_count_overrides)` — the third element covers `--placeholder`'s
  effect on VERIFY counts, see below. `declared_keys` is only the
  literally-emitted primary keys and gates
  `_render_expectation`'s `VERIFY ... WAS CALLED n TIMES` line — a
  narrower check than "is this key known to mockymock at all" is required
  here, or a `VERIFY` would be emitted for a key this TESTCASE mocked only
  as a non-primary alias of a shared site, which the run command's own
  `VERIFY_WITHOUT_MOCK` gate would then refuse. After real-data
  directives, every `mockymock_keys` entry not yet covered gets a
  placeholder directive too (reusing bundle-less `_directive_for`) — this
  unconditional "cover everything mockymock knows about" step is what
  keeps a mockymock-only key (a real key-set gap, or a boundary the bundle
  couldn't resolve, e.g. custprog's SQL FETCH above) from producing an
  UNMOCKED_* refusal instead of a scaffold a human can improve on.
- **Per-category body shape** (`_bundle_directive_for_group`, one real
  fixture group): a status-only boundary (OPEN/CLOSE/START/UNLOCK/DELETE)
  gets `_status_only_body` (a `FILE-STATUS IS` MOVE only when the status
  is non-"00"/"0" — file-op categories default to success implicitly, see
  `injector.build_site_dispatch`; SQL has no such default and always sets
  SQLCODE explicitly); a single-row READ/ACCEPT/WRITE gets
  `_single_row_body` (plain field MOVEs); a multi-row READ sequence gets
  `_read_body`'s hand-rolled `EVALUATE TRUE` / `WHEN <tally> = N` chain
  (mirroring `ROWS` sugar's own generated shape for consistency — `MOCK
  READ ... ROWS` grammar exists in the parser as of the ROWS/TERMINAL
  work above, but this bundle-driven scaffold deliberately still emits
  its own hand-rolled block rather than that syntax; see this section's
  own note above); a multi-row SQL FETCH gets real `ROWS (...)` sugar
  via `_sql_rows_directive` (`_sql_wants_rows` decides single vs. multi).
  Values render through `_bundle_rendered_value`: numeric-family
  `FieldSpec` categories render bare, everything else quoted and escaped.
  A POINTER-family field gets `SET <field> TO NULL` in a mock body, and
  a comment instead among a TESTCASE's own setup lines (the caller's USING
  values, `_entry_parameter_lines`), which take only MOVE: the `.cut`
  parser refused the SET there (TPMSA000, 2026-10-27), and the per-case
  reset already sets it to NULL. An INDEX field gets no
  line at all (`_row_move_line`, 2026-10-12): the bundle lays both out as
  numeric fields holding `0`, and `MOVE 0 TO <pointer>` is a cobc compile
  error (LESERV's `CALL 'CEEHDLR' USING HANDLER-ROUTINE ...`). An
  `alphanumeric-edited` field's value is the record's bytes (its edited
  image), so it is moved by reference modification, `MOVE "N8/DF/B3" TO
  IN-AE(1:)`; a plain MOVE edited it again (#277).
- **`_read_body`'s `WHEN OTHER` branch also replicates the source `AT END`
  clause's own constant-valued statements**, not just the FILE STATUS
  field (`_replicated_at_end_statements`, via `_is_safe_literal_source`
  for MOVE and `_replicated_set_lines` for SET): the splicer replaces the
  *whole* READ statement (see `splicer/orchestrator.py`'s own module
  docstring), which deletes the real `AT END MOVE "Y" TO WS-EOF`
  idiom along with it — a mock that moves only the FILE STATUS field never
  flips the program's own application-level EOF flag, so its `PERFORM ...
  UNTIL WS-EOF = ...` loop never terminates (an infinite loop, found via a
  real Docker CI run against `examples/fixtures/FIXTUREDEMO`, not by
  `mockymock lint`, which is static and cannot see a splice-time no-op).
  **Both spellings of that idiom are covered**: the literal `MOVE`, and
  the condition-name `SET WS-FIN-FICHIER TO TRUE` against an `88`
  (`_CONSTANT_SET_TYPES` = `TRUE`/`FALSE`). SET was the later fix — it
  parses to a `SetStatement`, not a `MoveStatement`, so the original
  MOVE-only replication silently skipped it and shipped a `WHEN OTHER`
  carrying nothing but the FILE STATUS move and a TODO comment, hanging
  every generated scenario for any program using the condition-name
  spelling. A `SET` is skipped (leaving the TODO to flag it) when its
  `set_type` is not a constant (`TO` an identifier, `UP_BY`, `DOWN_BY`)
  or when it carries additional `groups` — a multi-group `SET A TO TRUE B
  TO FALSE`, where replicating only the first group would be a silent
  *partial* replication, worse than none.
  Whether the `WHEN OTHER` branch is emitted at all is gated on the
  *source* `AT END` clause existing, deliberately not on
  `fixture.terminal` alone: a file with no `FILE STATUS` clause (e.g.
  `examples/invupdt/INVUPDT.cbl`'s `INV-FILE`) has `terminal is None`
  correctly (cobol-parser's `_resolve_status_field`), but the program's
  own `AT END` handler still fires every time the sequence exhausts and
  still needs replicating. Only a `MOVE` whose source is a quoted
  string/numeric literal or figurative constant is replicated from the AST
  — never a bare identifier, whose value in the mock's own splice-time
  context isn't the real program's runtime state.
- **A READ with no `AT END` clause whose loop ends on its FILE STATUS
  alone** (`PERFORM UNTIL WS-FS = "10"`, 2026-10-13) gets an end-of-file
  branch too: cobol-parser sets `fixture.terminal` only when the READ has
  an `AT END` handler, so this shape used to get rows and no `WHEN OTHER`
  -- the implicit `MOVE "00"` reported success forever and the generated
  suite hung. `ProgramContext.status_read_eof` (`_status_driven_reads`)
  names every file whose READs are all plain sequential reads (no `AT
  END`, no `INVALID KEY`, no `KEY IS`, and `READ ... NEXT` or a
  SEQUENTIAL-access SELECT) and that declares a FILE STATUS field;
  `_bundle_directive_for` gives such a fixture `terminal = {<status>:
  "10"}`, and when one of its READ sites runs in a loop it counts the
  end-of-file read (`CallCountOverride(count=rows + 1, cascades=False)` --
  the loop body still runs once per row, so the other boundaries in its
  paragraph keep their counts). A keyed/random READ is left alone: out of
  rows it would answer "23", not "10".
- **`DECIMAL-POINT IS COMMA` (issue #230)**: `ProgramContext.decimal_comma`
  (from `mockymock._decimal.decimal_point_is_comma`) makes
  `_bundle_rendered_value` (mock-body MOVEs, SQL `ROWS` values) and the
  Tier 2 `field_equals` EXPECTs write `9,99` instead of `9.99`. The parser's
  `_split_top_level` treats a comma between two digits as a decimal comma,
  not a separator, so `ROW 100,5, 125,62` and `( F = 1,25, G = 2 )` hold
  the values the program means (a separator comma is always followed by a
  space in COBOL).
- **A READ of a `RECORD VARYING ... DEPENDING ON` file sets the length
  item** (issue #214): `_row_move_lines` appends `MOVE <length> TO <item>`
  to every READ row (`_record_length_move`, cached per file on
  `ProgramContext.record_length_moves`), read from the FD record's
  `fd_clauses` metadata through cobol-parser's
  `VaryingLength.from_fd_clauses`. A real READ stores the length of the
  record it read there; leaving it at its VALUE (usually 0) put every
  generated record below the FD minimum. The bundle carries no per-row
  length (`declared_lengths` is not surfaced upstream yet), so every row
  reports the layout's full length clamped into the FD's range.
- **A field the program UNSTRINGs gets the delimiters it splits on**
  (2026-10-25, the RECFMT field run): `ProgramContext.unstring_layouts`
  (`_unstring_layouts`) maps each field split by exactly one
  `UNSTRING <field> DELIMITED BY "<literal>" INTO t1 ... tn` to that
  shape, and `_row_move_line` rebuilds the bundle's random value as one
  part per INTO target (`_delimited_value`): each sized to its target's
  PICTURE (shrunk to fit the field), digits for a numeric one, characters
  drawn from the seeded value. A field split two ways, or by a variable /
  several delimiters, keeps the bundle's value.
- **A SELECT / FETCH mock writes only its INTO targets** (issue #239):
  the bundle lays out every host variable of an EXEC SQL, the WHERE
  clause's input key included, so a SELECT mock overwrote the key the
  program had set and `--record-expectations` recorded the random text.
  `_sql_output_layout` keeps only the fields named by the statement's
  `into_variables` (cobol-parser's `ExecSQLStatement` / `FetchStatement`;
  null indicators are in that list), matching the fixture's line, else
  every SQL site its key prefixes; a statement with no INTO list leaves
  the layout alone. `examples/fixtures/FIXTUREDEMO.cut` was regenerated
  (it no longer moves into `WS-CUSTOMER-ID`).
- **A CICS mock writes only what the command returns** (issue #222):
  cobol-parser marks every EXEC CICS boundary BIDIRECTIONAL and lays out
  every resolved operand, so `_single_row_body` used to MOVE random text
  into `WRITE ... FROM(rec)`, a WRITE's `RIDFLD` and `SEND TEXT FROM(msg)`
  -- state the real transaction never touches, recorded as golden by
  `--record-expectations`. `_cics_output_layout` drops a layout field that
  only an input operand names (`_cics_operand_roles` over the statement's
  `options`, found by the fixture's line among the key's CICS sites): FROM,
  FILE/QUEUE/MAP/PROGRAM/TRANSID/... always; RIDFLD except on
  READ/READNEXT/READPREV; LENGTH/FLENGTH except on the commands that
  return a length (READ*, RECEIVE, READQ, RETRIEVE, GET, CONVERSE, WEB);
  COMMAREA on RETURN/XCTL (LINK's stays: the callee may update it);
  only ABSTIME on FORMATTIME; nothing on ASSIGN/INQUIRE/ADDRESS/ASKTIME.
  A field also named by a non-input operand of any statement for the key
  is kept.
- **CICS RESP/RESP2 answer NORMAL** (issue #253): the bundle lays the
  `RESP(item)`/`RESP2(item)` operands out as ordinary fields with random
  values, which sent every happy path down `IF WS-RESP NOT =
  DFHRESP(NORMAL)` and let `--record-expectations` record the error
  branch. `_single_row_body` drops those fields from the row and writes
  `MOVE 0 TO <item>` for each (`_cics_resp_names` over the fixture's
  statements), unless the scenario pinned the field to reach its branch
  (`_pinned_fields`: the leaf names in the scenario's
  `verification.fields`, threaded through `_bundle_directive_for_group` /
  `_bundle_directive_for` as `pinned`).
- **CICS browse loops end (#316).** A READNEXT/READPREV/READQ whose key
  has a site inside a loop whose UNTIL reads the command's own RESP field
  (or, one hop, a flag set from it: `_reply_watched_names`) gets
  `_cics_loop_end_lines`: `IF <tally> > 1 / MOVE 20 TO <resp>` (ENDFILE;
  26 ITEMERR for READQ TS, 23 QZERO for READQ TD), unconditional without
  a tally, and a `VERIFY ... 2 TIMES` (`CallCountOverride(count=2)`).
  Every site the key's MOCK answers is checked, so a priming READNEXT
  before the loop works; sites needing different replies get a TODO.
  Applied in the bundle row, the placeholder bodies and `--placeholder`.
- **An AT END clause the splice re-runs is not copied at all** (issue
  #209): `_at_end_handling` asks `analysis.clause_bodies.lift_clause_bodies`
  first; when the splice will run the READ's own AT END clause after the
  mock, the exhaustion branch only reports end of file -- `fixture.terminal`'s
  status MOVE, or `MOVE "10" TO UT-MOCK-STATUS` for a file with no FILE
  STATUS field -- plus a comment saying so. Copying it too would run it
  twice. The replication / lift below is now the fallback for a clause the
  splice cannot lift (or a scaffold built without a `ProgramContext`).
- **AST replication is all or nothing** (issue #217): when any statement in
  the `AT END` clause is not one of the two replicable shapes,
  `_replicated_at_end_statements` returns nothing, so the whole clause is
  lifted (below) or flagged with the TODO. It used to replicate the literal
  `MOVE "Y" TO WS-EOF` and silently drop `MOVE WS-READ-CNT TO
  WS-TRAILER-CNT` beside it, and `run --record-expectations` then recorded
  goldens for behaviour the program does not have.
- **When the AST-driven replication comes up empty, the clause's own source
  text is lifted verbatim instead** (`_lifted_at_end_lines`, 2026-09-04).
  The `*> TODO` comment that used to be emitted there is not a visible gap
  so much as a silently hanging test: a reader who leaves it in gets a
  30-second executor timeout with no diagnosis, because the program's own
  loop guard is never set. The lift is a *slice of the program's own
  source* — exactly the text the splice is about to delete — not a
  re-render limited to the shapes an AST walk knows about, which is what
  makes it general enough to cover identifier-sourced MOVEs, `ADD`, `IF`,
  `PERFORM`, and everything else a real `AT END` clause holds.
  `ProgramContext` (the normalized lines plus
  `splicer.source_map.collect_boundaries`' statement starts — the SAME two
  inputs the splicer's own `statement_span` uses, so the lifted text cannot
  drift from the deleted text) is threaded from `_cmd_generate` through
  `scaffold_cut`. `_extract_at_end_imperative` locates `AT END` positionally
  with words scanned OUTSIDE quoted literals (so a `DISPLAY "AT END OF
  FILE"` is never mistaken for the clause) and cuts at the first of `NOT AT
  END` / `END-READ` / `INVALID KEY` / `NOT INVALID KEY` / a
  sentence-terminating period (a period followed by whitespace or
  end-of-text — COBOL's own rule, which is also what keeps a numeric
  literal's decimal point from being read as one). A lifted line carries a
  `*>` provenance comment naming the source line, since a generated file a
  human reads should not silently contain code that did not come from the
  fixture data. The `*> TODO` remains the fallback when no `ProgramContext`
  was supplied or the clause could not be located.
- **Per-site counts from a 3.1 bundle.** cobol-parser before 3.1 gave
  every fixture its own `call_count` (1 for a CALL or a status-only
  boundary; the row count, plus one for the end-of-file call when the
  statement has AT END, for a fed one). From 3.1 (#363) it writes one per
  `(category, key)` and only when control flow makes it exact. Everything
  below (`_merged_call_counts`, `_conditional_call_count_keys`, the
  MQGET/DL/I loop-end and FILE STATUS end-of-file overrides) starts from a
  count per mocked key, so `_with_site_call_counts` first gives each key
  the bundle left uncounted its per-site counts back; the analysis then
  demotes or corrects them as it always did. A count the bundle wrote is
  kept, and an `error status:` scenario is left alone (the bundle drops
  its counts because the failure path makes them untrue). On an older
  bundle every key is counted already, so nothing is added.
- **Expectations** render via `_render_expectation(expectation,
  declared_keys, call_count_overrides=None, counted_boundaries=None)`:
  tier 1 (`call_count`) →
  `VERIFY <cat> <key> WAS CALLED n TIMES`, gated on `declared_keys` as
  above, `n` normally `expectation.value` but see `--placeholder`'s
  `call_count_overrides` below (and #372: `_once_per_site_counts` sets the
  override of a one-shot category -- `_ONE_SHOT_CATEGORIES`: CALL, OPEN,
  CLOSE, ... -- to its number of reachable sites when every one of them is
  in the exact scope, so a case that stops right after a failing OPEN
  pins it once rather than the bundle's whole-run count); tier 2 (`field_equals`) → `EXPECT <name>
  TO BE <value>`, the value rendered by `render_expect_value` with the
  field's PICTURE (`ProgramContext.pictures`, from `field_pictures`), so a
  folded `-3`/`1.5`/`007` in a `PIC X` field is quoted -- rendered bare it
  failed on the generated suite's first run (2026-09-28); tier 3 (`stub`) → a `*> STUB EXPECT ...` comment. A
  `"CATEGORY:KEY"`-shaped boundary-level `ref` (`_is_boundary_level_ref`
  detects the colon, since COBOL names never contain one) renders as
  `*> STUB EXPECT <CAT> <KEY>` — the way a MOCK/VERIFY for that boundary
  reads — and is dropped ONLY when this same TESTCASE actually emits a live
  `VERIFY ... WAS CALLED` for it (`_rendered_call_count_refs`, which
  excludes both keys with no MOCK directive of their own and counts demoted
  to a comment by a `--placeholder` downgrade). It used to be dropped
  unconditionally on that "already covered by its own call_count VERIFY"
  reasoning, which is simply false for an OUT-direction boundary: every
  `WRITE:` stub the bundle produced under `--scenarios all` vanished, so
  the analysis knew something the generated `.cut` never said. A `*>`
  comment is inert, so surfacing it can never break the file; dropping it
  opened a gap between what the analysis knew and what reached the file,
  which is the one thing a scaffold must not do. A WRITE/REWRITE/RELEASE
  boundary (`_RECORD_OUTPUT_CATEGORIES`) instead renders as `*> STUB
  EXPECT <record> -- last record written by WRITE <record>`: the record
  area holds the last record written (a mocked `WRITE r FROM y` keeps its
  implicit MOVE), so `run --record-expectations` (and so `init`) fills it.
  As `STUB EXPECT WRITE OUT-REC` it named no data item, the scanner
  dropped it, and a read-process-write scaffold never got an output
  assertion (issue #255). Every other boundary keeps the two-token form,
  which does NOT match the scanner's data-name grammar
  (`analysis/stub_expectations.py`'s `_STUB_RE`); the scanner reports such
  a line as skipped (`not a data name`, `_ANY_STUB_RE`) rather than
  mistaking `READ` for a data item or dropping it silently -- see
  `analysis.md`'s stub-expectation scanner for how a human promotes a real
  data-name stub comment to an `EXPECT`.
- **Bundle `unresolved` notes** (issue #331): `FixtureBundle.unresolved` and
  each `BoundaryFixture.unresolved` (what cobol-parser could not generate,
  e.g. a header/detail FD generated through its first 01 record only) were
  parsed and dropped. `_scaffold_with_bundle` now writes each fixture's
  entries as `*> NOTE:` lines directly above its MOCK
  (`_bundle_mock_directives`), the bundle-level entries not already shown
  at a fixture under TESTSUITE, and prints every entry once on stderr
  (`mockymock generate: note: ...`) -- `init` composes `generate`, so it
  prints them too.
- **Unverified-scenario notes** (`_verification_comment_lines`, 2026-09-04):
  cobol-parser's bundle now carries a `Scenario.verification` verdict --
  whether that scenario's own generated data actually satisfies the branch
  it is named for. A scenario name is a claim; before that verdict existed
  the only way to check it was `mockymock run --trace` on every case. An
  `unverified` verdict renders as a `*> UNVERIFIED:` comment block directly
  above the affected TESTCASE, listing each non-satisfied field verdict and
  each path gap. A `verified` scenario gets nothing -- a note on every case
  would be noise and would train readers to skip the ones that matter -- and
  a bundle with no `verification` key at all (an older v1 bundle) is read as
  "no verdict recorded", never as unverified.
- **Lint gate**: `tests/integration/test_generate_with_data_lint_gate.py`
  generates a `.cut` for every corpus program across all three
  `--scenarios` modes (happy/branches/all) and asserts `mockymock lint`
  (via `cli.checks.run_static_checks`, Docker-free) finds zero problems —
  "a generator that emits a refusable `.cut` is worse than none."

#### Scaffold corrections from the 2026-10-05 bug hunt (#141-#145, #148, #150)

All in `dsl/generator.py`; `ProgramContext` now also carries `looped`,
`program`, `neutralized_goto` and `name_counts`.

- **Reachability per scenario (#143).** Only boundaries reachable from the
  scenario's entry (`ProgramContext.reachable_from`, the same walk lint
  uses) get a `MOCK`; anything else was an `UNMATCHED_MOCK`.
- **Loops (#141).** `analysis/loops.py` finds sites inside a looping
  PERFORM (UNTIL/VARYING/TIMES, inline or via its target). A looped cursor
  `FETCH` is mocked with `ROWS` and verified `rows + 1` times; a `READ`
  outside any loop is verified once per site.
- **Summed counts (#142).** One key called from several sites gets one
  `VERIFY` with the summed count; if any of those sites is nested in an
  IF/EVALUATE/loop the count is demoted to a `*> VERIFY ... <count not
  exact by construction -- reason>` comment.
- **Conditional sites (#160).** The bundle counts every site once per
  scenario whether or not its branch runs, so a count is kept only when
  every site of its key is in `analysis/exact_counts.py`'s
  `exact_count_scope` for the entry: top level of its paragraph (or an
  inline PERFORM body there), in a paragraph reached through top-level
  PERFORMs only (looping ones only for READ/RETURN -- see #290 below)
  and by nothing else -- no PERFORM inside an
  IF/EVALUATE/AT END, no GO TO, SORT/XML procedure, or fall-through from
  a GO TO target. A PERFORM in a branch that ends with `STOP RUN`/`GOBACK`
  doesn't count against its target. Everything else is demoted the same
  way, including a per-row CALL behind a loop's own `IF NOT EOF` guard.
  A site after a statement that may end the run (a STOP RUN/GOBACK/EXIT
  PROGRAM/CICS RETURN in an IF/EVALUATE/AT END body, or a conditional or
  looping PERFORM of code holding one) is out of scope too, since the
  error-status scenarios take that branch (2026-10-27); a paragraph the
  stopping branch itself PERFORMs first keeps its count. A `PERFORM
  <section>` counts only its range (`_section_range`: not the members
  after an EXIT SECTION / GOBACK / GO TO), and a member the entry's
  section range falls into that a straight PERFORM also names runs twice.
- **READ with no AT END in a loop (2026-10-27).** The bundle's READ count
  is its row count, right only for a read-until-end-of-file loop. A READ
  with no AT END clause read inside a loop or under a condition (a keyed
  READ in `PERFORM X 3 TIMES`, NIST IX301M) is demoted
  (`_NO_END_READ_REASON`); a FILE STATUS loop keeps the count
  `_status_read_eof` gives it.
- **Sites that run more than once a pass (#290).** The bundle (cobol-parser
  2.x) gives every site `call_count` 1 however often it runs, so for every
  category but READ/RETURN `exact_count_scope` no longer treats a looping
  PERFORM as a straight edge: its target, any PERFORM inside an inline
  loop's body, the inline loop body's own statements, and a paragraph
  PERFORMed by two or more straight statements are all out of scope, and
  their counts are demoted with `_LOOPED_SITE_REASON`. READ/RETURN are
  checked against `exact_count_scope(..., loops_exact=True)` (the older
  scope, looping PERFORMs as straight edges), since their counts are the
  bundle's row model of the read loop.
- **Sites the entry never reaches (2026-10-14).** The bundle also counts
  a key's sites in paragraphs nothing PERFORMs from the entry (a CICS
  `HANDLE CONDITION` target, dead code), and #142's sum included them:
  ACCTINQ's scaffold verified its CICS RETURN `2 TIMES` (one in
  0000-MAIN-PROCESS, one in the NOTFND handler) and failed its own first
  `init` run with "got 1". A key with any site outside the entry's
  reachable set is demoted (`_UNREACHED_SITE_REASON`); READ/RETURN keep
  their count, since theirs is the largest per-site count, not a sum.
- **Field names (#144).** Fixture fields arrive as `RECORD.FIELD`; rows and
  bodies use the leaf (or `FIELD OF RECORD` when the leaf is ambiguous) and
  an `EXPECT` whose leaf is ambiguous becomes a stub comment.
- **DL/I get-next loops (#145).** A looped `GN`/`GHN`/`GNP`/`GHNP` mock
  sets `DIBSTAT` to `GB`/`GE` after its first call, so the scan ends.
  Every DLI site the key's MOCK answers is checked for a loop (#315): the
  usual priming GN before the loop is the first site seen and is not
  itself looped.
- **SQL status-only bodies (#148).** OPEN/CLOSE/COMMIT-style bodies set
  `SQLCODE` to 0 when the fixture names no SQLCODE.
- **No entry (#150).** A scenario with `entry=''` (IMS `ENTRY 'DLITCBL'`
  programs) falls back to the first named PROCEDURE DIVISION section
  or paragraph by source line (`_first_paragraph`) -- sections count
  since #238, so a section-structured program whose main line sits
  unnamed under `A000-MAIN SECTION.` is entered with `PERFORM A000-MAIN`,
  not with the first paragraph of a later section; `generate --with-data` exits 1 when no scenario
  became a TESTCASE. A `CALL 'CBLTDLI'` get loop is covered by #156 below.
- **Looped MQGET / CBLTDLI get calls (#156).** When a CALL sits in a loop
  whose UNTIL reads the call's own reply (`analysis.loops.loop_guard_words`,
  matched against the argument and every name declared under it, 88s
  included -- plus, one hop out (#188), any flag the CALL's own paragraph
  writes by `SET ... TO TRUE` or `MOVE` inside an IF/EVALUATE whose
  condition reads the reply, `analysis.loops.names_set_on_reply`, with an
  88's own field and sibling 88s: DEPTMQC's `UNTIL NO-MORE-MSGS` set under
  `WHEN MQ-REASON-CODE = MQRC-NO-MSG-AVAIL`), the mock reports end of data
  after its row: `MOVE 2` /
  `MOVE 2033` into MQGET's CompCode/Reason (8th/9th USING arguments), or
  `GE`/`GB` into bytes 11-12 of a CBLTDLI/CEETDLI get call's PCB (GU/GHU/
  GNP/GHNP -> GE, GN/GHN -> GB; the function code is read from the first
  argument's VALUE literal). The reply is gated on `IF <tally> > 1` when a
  tally is known, unconditional in the bundle-less scaffold, and its VERIFY
  becomes 2 unless the row itself already moves the end status. A GU
  through an I/O PCB ends with `QC` (no more messages) instead of `GE`:
  `_is_message_pcb` takes a PCB for the I/O PCB when the program sends
  through it (a three-argument ISRT, PURG or CHNG) and never reads it with
  a get-next. One MOCK answers every site of its key, so when the key's
  sites need different replies (an IMS MPP's GU loop plus its ISRT through
  the same CBLTDLI, or a GN loop plus an ISRT) the end reply is gated on
  the function code the call passed, read from the key's scaffolded
  `CAPTURE ARG 1` (`IF UT-CBLTDLI-TALLY > 1 AND UT-CAP-CBLTDLI-1 = "GU"`,
  `_dli_end_lines_by_function`), and the key's VERIFY count is not fixed,
  since the other functions' calls count too. Without that capture (the
  function codes' layouts differ) or with a non-literal get function, the
  body gets a `*> TODO` comment instead.
- **A CICS LINK server gets its commarea (#245).** The reset zeroes
  EIBCALEN before every case, and since #215 a mocked `EXEC CICS ABEND`
  ends the run, so a LINK server's `IF EIBCALEN < LENGTH OF DFHCOMMAREA
  EXEC CICS ABEND` guard ended every generated happy path before the
  READ/REWRITE its VERIFYs counted. `_commarea_setup_lines` (stored as
  `ProgramContext.setup_lines`) finds an `IF` whose condition names
  EIBCALEN and whose THEN branch ABENDs, in a program declaring
  DFHCOMMAREA, and both scaffolds then write `MOVE LENGTH OF DFHCOMMAREA
  TO EIBCALEN` before every case's PERFORM, as a real LINK passes it. An
  `IF EIBCALEN = 0` first-time path (pseudo-conversational) is not an
  ABEND guard and gets nothing.
- **MQ calls answer MQCC_OK / MQRC_NONE (#205).** By the MQI's fixed
  convention CompCode and Reason are an MQ call's last two USING
  arguments; `_mq_success_reply` replaces the fixture row's random numbers
  there with `MOVE 0` for every `site.is_mq` CALL. The bundle-less
  placeholder (`directive_snippet`: lint's fix text, `--fill`, and the
  mocks `generate --real` writes for a real subprogram's MQ calls) does the
  same since 2026-11-01; before, it set only RETURN-CODE. A random CompCode sent
  the `IF WS-COMPCODE NOT = MQCC-OK ... GOBACK` idiom (MQCC-OK is a data
  item the solver cannot see) down the failure exit on the first call, so
  the happy path never ran and its later `VERIFY ... 1 TIMES` failed. With
  success answered, an MQGET in any UNTIL loop also gets the #156 end
  reply, whatever its guard reads: a drain loop's flag is set *from* the
  2033 reply (`WHEN WS-REASON = MQRC-NO-MSG-AVAILABLE SET DRAIN-DONE`), so
  without it the loop never ends. A `PERFORM n TIMES` loop (no guard
  words) is still left alone. (The issue's option (b), demoting VERIFY
  counts for sites after an `IF ... GOBACK`, is not implemented.)
- **DL/I calls answer a blank PCB status (#317).** The DL/I counterpart:
  `_dli_success_reply` appends `MOVE SPACES TO <pcb>(11:2)` (the PCB is a
  CBLTDLI/CEETDLI call's second USING argument) after the fixture row and
  before any #156 end reply, in the bundle row, the `--placeholder`
  downgrade and the bundle-less body alike. A random status such as "PO"
  ended a `PERFORM UNTIL PCB-STATUS NOT = SPACES` get loop on the first
  call and failed the scaffold's own `VERIFY ... 2 TIMES`.
  `_row_already_ends` therefore never credits a DL/I row with ending the
  loop.
- **CALL mocks leave a loop's control items alone (#286).** A CALL
  (or DYNCALL / DLI) passing its enclosing loop's own counter -- `CALL
  "FMTLINE" USING WS-IX WS-LINE` inside `PERFORM VARYING WS-IX ... UNTIL
  WS-IX > WS-COUNT` -- had that argument laid out as a fixture field, and
  the row's `MOVE 0 TO WS-IX` reset the loop on every call (hang until
  `--timeout`). `_without_loop_control` drops every layout field naming a
  VARYING / AFTER item or UNTIL word of an enclosing loop
  (`loops.loop_control_words`; `LoopGuard.varying` holds the VARYING /
  AFTER items) and leaves a `*> TODO` naming it. A guard that waits on the
  call's own reply (MQGET / DL/I get, #156) keeps its reply fields.
- **ACCEPT control-card loops end (#263).** `MOCK ACCEPT <target> ROWS (
  ... ) TERMINAL ( <target> = "END" )` feeds SYSIN cards in order (ACCEPT
  is in `SEQUENCED_CALL_CATEGORIES`, so TERMINAL is mandatory). In the
  scaffold, `_accept_loop_end_lines` handles an ACCEPT whose loop's UNTIL
  compares the target to a literal (`loops.loop_exit_literal`, read from
  `LoopGuard.until_text`): the row's value answers the first call and
  `IF UT-ACCEPT-<key>-TALLY > 1 MOVE <literal> TO <target>` the rest
  (`VERIFY ... 2 TIMES`); a bundle-less or `--placeholder` body moves the
  literal outright (`VERIFY ... 1 TIMES`). A guard on the target with no
  literal to match gets a TODO.
- **Placeholder READ/RETURN mocks report end-of-file (#302).** A
  bundle-less `MOCK READ`/`MOCK RETURN` for a statement with an AT END
  clause was an empty body, so a `PERFORM UNTIL WS-EOF = "Y"` read loop
  ran until `--timeout` from lint's suggested fix, `generate --fill` and
  `--per-paragraph`. `_end_of_file_placeholder` now gives the FILE_OP body
  (`_directive_for`, and through it `directive_snippet`) its exhaustion
  lines: with a `ProgramContext`, exactly a bundle READ fixture's
  (`_at_end_handling` / `_read_exhaustion_lines`); without one (lint),
  `MOVE "10"` into the file's FILE STATUS field or else `UT-MOCK-STATUS`,
  plus the clause's replicable statements. `directive_snippet` takes the
  program's `file_status_fields` (lint's gate passes them). This is also
  what ends a SORT OUTPUT PROCEDURE's `RETURN ... AT END` loop (#262): the
  bundle never lays out RELEASE / RETURN, so they always take the
  placeholder path, and `_warn_on_key_mismatch` no longer calls that a
  "should not happen" mismatch (`_BUNDLELESS_CATEGORIES`).

### `--rows` / `--placeholder` on the bundle-driven scaffold (unify-with-data Task 4)

`scaffold_cut`'s fourth parameter, `placeholder_keys: frozenset[tuple[str,
str]] = frozenset()` (bundle-side string category paired with the
fixture's own key, e.g. `("READ", "ORDER-FILE")` — matching how the CLI
uppercases `--placeholder CATEGORY:KEY`'s category but leaves the key
case-sensitive), only has an effect with a bundle; without one every site
already gets a placeholder body. `--rows N` doesn't touch `generator.py`
at all — it maps to `DataGeneratorOptions(rows=N)` on the
`ProgramFixtureGenerator` construction in `cli/main.py` (`_cmd_generate`'s
`--with-data` branch, mirroring `_cmd_fixtures`), so by the time a bundle
reaches `scaffold_cut` its row counts are already baked in exactly like
`--fixtures FILE`'s are — hence `--rows` combined with `--fixtures` is a
clean CLI-level rejection (source of truth: `mockymock/cli/main.py`, not
this module).

**The downgrade** (`_bundle_directive_for`/`_bundle_directive_for_group`):
a fixture named by `placeholder_keys` gets its body stripped of seeded
data but stays MOCKED — never dropped to nothing, since an unmocked
reachable site is a refusal, not a scaffolding choice. For every category
whose ordinary body carries no loop-termination machinery
(OPEN/CLOSE/START/UNLOCK/DELETE's status-only body, CALL/DYNCALL/ACCEPT/
CICS/DLI, a single-row SQL fixture), the downgrade reuses the ordinary
bundle-less placeholder body (`_placeholder_body_for`, factored out so
the bundle-driven and bundle-less paths can never drift). Two categories
get a DEDICATED downgrade instead, because their non-downgraded body is
what makes the program's own loop actually terminate, and the
runnable-by-construction invariant covers every generated `.cut`, not
just the no-`--placeholder` ones:

- **READ**: downgrades to `_read_exhaustion_lines(...)` — the exact same
  helper `_read_body` uses for its own `WHEN OTHER` branch AND for an
  entirely empty `sequence` (a `--rows 0` bundle, or one of cobol-parser's
  own "empty input" scenario family fixtures) — an "immediately at end"
  body (`fixture.terminal`'s status MOVE(s) plus any safely-replicated
  `AT END` MOVEs), never an empty one. An empty downgraded body would
  silently drop the program's own EOF-flag idiom and hang its `PERFORM
  ... UNTIL <eof-flag>` loop forever — the exact class of bug commit
  `3ad3378` fixed for the ordinary multi-row case, closed here for the
  zero-row and downgraded cases too.
- **SQL**, only when this fixture would otherwise have used `ROWS` sugar
  (`_sql_wants_rows`): downgrades to `_SQL_ROWS_EXHAUSTED_BODY` (`["MOVE
  100 TO SQLCODE"]`, mirroring `splicer/injector.py`'s own hardcoded
  `MOCK SQL ... ROWS` exhausted-branch value), not the ordinary SQL
  placeholder's `MOVE 0 TO SQLCODE` (permanent "more rows available"),
  which would hang a `PERFORM UNTIL SQLCODE = 100` cursor-fetch loop the
  same way an empty READ body would.

**VERIFY recompute** (`CallCountOverride`, fix round 2): a downgrade that
changes what a mock body actually does at runtime can also change how
many times the program actually reaches it — a downgraded READ signals
EOF on its very first call, so a `PERFORM ... UNTIL <eof-flag>` loop
calls it exactly once, not the bundle's original un-downgraded sequence
length. Rendering the bundle's stale original count would pin a `VERIFY
... WAS CALLED N TIMES` the generated file cannot itself satisfy — the
runnable-by-construction invariant covers assertions too, not just mock
bodies. `_bundle_directive_for`/`_bundle_directive_for_group` compute a
`CallCountOverride(count=1)` for a downgraded READ that still carries a
real termination signal (`fixture.terminal` or a replicated `AT END`
MOVE/SET) and for a downgraded SQL-ROWS fixture unconditionally (its body is
always an unconditional literal MOVE, no replication gap possible); when
a downgraded READ's exhaustion body carries NO termination signal at all
(no `FILE STATUS` field and nothing `_replicated_at_end_statements` could
safely replicate), `CallCountOverride(demote_reason=...)` instead — the
real count is not knowable by construction. `_bundle_mock_directives`
collects these per `(category, key)` into `call_count_overrides` (same
seam that decided each body, so `_render_expectation` never re-derives
the downgrade decision); `_render_expectation` renders `override.count`
in place of `expectation.value` when present, or — for a `demote_reason`
— a `*>` comment instead of a `VERIFY` line at all: `*> VERIFY <directive>
WAS CALLED <count not exact by construction after --placeholder downgrade
-- <reason>>`. `count=1` is exact ASSUMING the program stops reading/
fetching this boundary once its end-of-data signal fires — the same
assumption the rest of this engine already makes about every
program-flow-driven call count; a program that reads the same file/
cursor a fixed number of times unconditionally, ignoring that signal,
would still see a stale count.

**This recompute covers only the downgraded boundary's OWN call count —
it is not a general re-derivation of every VERIFY in the TESTCASE.**
Every other category's call count is program-flow-driven (how many
times the PROCEDURE DIVISION reaches that statement) and is left exactly
as the bundle computed it, even when that count itself depends on how
many times the now-downgraded loop executes — e.g. a `CALL` made once
per row inside the same `PERFORM ... UNTIL <eof-flag>` loop as a
downgraded `READ`. A `--placeholder`-downgraded READ that now signals
EOF on call 1 makes that loop body (and anything it calls) run far fewer
times than the bundle's original, un-downgraded sequence length assumed
— but nothing recomputes the `CALL`'s own `VERIFY ... WAS CALLED N
TIMES` to match. This is inherited behavior, not new here: every in-loop
call count was already heuristic (derived from the bundle's generated
sequence length, not the downgraded body), `--placeholder` just makes it
easier to reach in practice. Review the VERIFYs on any other boundary
inside the same loop as a downgraded one before trusting the generated
file.

Deliberately NOT covered by any of this: `--rows N` combined with
`--scenarios all`'s fixed "empty input" family, which pins its own
sequence length to 0 on the cobol-parser side regardless of `--rows` (see
`cobolparser.generators.scenarios._empty_input_scenario`) — `--rows`
changes the generator's *default* row count, not a scenario family that
deliberately overrides it.

# Gotchas

- **`MOCK MQ` has no `MockCategory.MQ`.** It is pure `.cut`-syntax sugar for
  `CALL`, resolved in `parser._resolve_category` (`cat == "MQ"` returns
  `MockCategory.CALL`). If you `grep` the model for MQ handling and find
  nothing, that's correct — MQ only exists in the parser's regex layer and
  in `generator.py`'s `is_mq` branch that re-adds the `MQ` keyword for
  scaffold readability. Do not add a `MockCategory.MQ`; it would break the
  `(category, key)` matching invariant described in the `MockCategory`
  docstring.
- **`DYNCALL` is never spelled `DYNCALL` in a `.cut` file.** Both `MOCK` and
  `VERIFY` spell it `CALL` with a bare (unquoted) key; the parser
  distinguishes it from static `CALL` purely by whether the key was quoted
  (`bare_key=True` passed into `_resolve_category`). A future editor adding
  a new bare-key category must extend `_BARE_CATS` in `parser.py` **and**
  add the category to `FILE_OP_CATEGORIES`/`FLOW_CATEGORIES`/handle it
  explicitly in `_resolve_category` and `MockDirective.describe()`, or it
  will silently fall through (PARAGRAPH/SECTION, added 2026-07-20, ride
  `MockCategory(cat)` in `_resolve_category` because their enum values
  equal their keywords, and render bare in `describe()` via
  `FLOW_CATEGORIES`).
- **A missing `END-MOCK` still swallows lines until EOF before erroring.**
  The unterminated-body check fires only at end of file (with the opening
  MOCK's line number); everything between the `MOCK` line and EOF —
  including what would otherwise be `TESTCASE`/`PERFORM` text — has already
  been absorbed into `body_lines` by the time the error raises. Mid-file,
  a forgotten `END-MOCK` therefore usually surfaces as this EOF error, not
  as an error at the next directive.
- **Bare keys are case-normalized, quoted keys are not.** `MOCK OPEN
  inv-file` and `MOCK OPEN INV-FILE` parse to the same key (`.upper()`
  applied); `MOCK SQL "select"` and `MOCK SQL "SELECT"` are different keys
  because quoted text is preserved exactly.
- **v1 → v2 naming residue:** `MockDirective.program_name` and
  `VerifyDirective.program_name` are both explicitly documented as "v1
  compat: the CALL key" — they alias `.key` and are only semantically
  meaningful when `category is MockCategory.CALL`; reading `.program_name`
  off a `READ`/`SQL`/etc. directive returns the key but the name is
  misleading for those categories.

# See Also

- [splicer](splicer.md) — consumes `MockTestSuite` to instrument COBOL source
- [cli](cli.md) — `mockymock generate` calls `scaffold_cut`; `mockymock run` calls `parse_cut`
- [analysis](analysis.md) — `stub_expectations.py`'s raw-text scan for `*> STUB EXPECT` comments
- [report](report.md) — `record_rewrite.py`, which rewrites a stub comment into a real `EXPECT` line

### `DFHRESP(...)` in .cut text (2026-10-13, #169)

`parse_cut` runs `splicer.cics_resp.expand_dfhresp_text` over every
non-comment line before matching it, so `DFHRESP(<condition>)` in a mock
body, a ROWS/TERMINAL value, a setup MOVE or an EXPECT value becomes its
EIBRESP number exactly as it does in program lines (GnuCOBOL has no CICS
translator, so an unexpanded one in spliced mock code was a raw cobc error
naming no .cut line). Calls inside a string literal or after an inline `*>`
stay text. A condition name not in `DFHRESP_VALUES` is a `CutParseError`,
so `lint` reports it.

## `real_branches.py` -- lookup cases for real subprograms (2026-11-02)

`link_real_programs` (`generate --real`) keeps each READ placeholder's body
and calls `add_found_cases`: for every `IF <record field> = <LINKAGE item>`
(`key_matches`, resolved through cobol-parser's `ProgramLayoutIndex`) on a
file the real program READs, one more TESTCASE, a copy of the first case,
whose `MOCK READ <file>` returns the matching record once (`MOVE <item> TO
<field>`, other fields from a seeded `ValueFactory`) and then the
placeholder's end-of-file body. Design:
[docs/2026-11-02-real-dynamic-call-design.md](../docs/2026-11-02-real-dynamic-call-design.md).

## Generated DL/I, MQ and CICS replies (2026-11-02 stress test)

- One `MOCK CALL "CBLTDLI"` answers every DL/I call, so with several
  fixtures `_dli_rows_directive` dispatches on the captured function code
  (and `UT-PASSED-ARG-2` when one function is used on several PCBs): each call
  gets the row the bundle generated for it, and a pinned PCB status is kept.
- The end-of-data reply (`_call_loop_end_lines`) goes only to the calls a
  loop guard watches; a function/PCB gate is used when another call of the
  key would otherwise receive it (`_dli_needs_gate`), the plain tally gate
  when the only other call is a priming call.
- `_mq_success_reply` leaves a CompCode / Reason the scenario pinned.
- `mockymock/copybooks/system/` ships DFHAID and DFHBMSCA, searched after the
  user's own copybook paths (`discovery.with_system_copybooks`).
