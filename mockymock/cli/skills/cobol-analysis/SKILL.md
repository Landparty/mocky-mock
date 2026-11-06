---
name: cobol-analysis
description: Answer questions about COBOL, JCL or copybook source by running the cobol-parser CLI instead of reading the source by eye. Use when a task involves a .cbl/.cob/.cpy/.jcl file or a mainframe checkout — "what does this program do", "is this paragraph used", "what breaks if I change this field", "decode this record image", "grade this codebase", "what are the byte offsets", or any edit to COBOL source that needs checking afterwards.
---

<!--
Maintainer note: this file is the one source of the `cobol-analysis`
skill. mocky-mock ships it, byte for byte, as
mockymock/cli/skills/cobol-analysis/SKILL.md (its cobol-testing plugin and
`mockymock skills install`), so keep it free of anything true only inside
this repo. Edit it here, then run mocky-mock's
`scripts/sync_cobol_analysis_skill.py`; that repo's tests fail on a copy
that has drifted from this one. tests/unit/test_cobol_analysis_skill.py
checks every subcommand and flag it names against the real CLI.
-->

# Analyzing COBOL with cobol-parser

COBOL defeats the usual read-the-file approach in three specific ways, and
each has a subcommand that answers it exactly:

* **A program does not fit in context.** 20,000 lines is ordinary. Reading the
  first 500 tells you nothing about the branch that matters.
* **The facts are not local.** A paragraph's meaning lives in a DATA DIVISION
  entry 4,000 lines above it, in a copybook that is not in the file, and in a
  JCL DD card in another directory.
* **Byte math is exact and unforgiving.** `PIC S9(7)V99 COMP-3` occupies 5
  bytes, packed, with the sign in the low nibble. Do not derive this by hand;
  `data-items` and `decode` already know.

So: **run the tool, cite its output, and read its caveats.** Prefer a
subcommand over reading source whenever one covers the question.

## Setup

When a `cobol` MCP server is connected (`cobol-parser mcp`), prefer its
tools for those questions (`program_brief` first, then `explain_symbol`,
`callers_of`, `record_layout`, `lint` and `read_source`; across programs,
`codebase_overview`, `callers_of` with a program name, `impact_of_change`
and `where_from`): they answer from cached parses, cite every fact as
`file:line` on disk, and list what they could not check under `caveats`.

The CLI is `cobol-parser` (`pip install cobol-parser`; from a cobol-parser
checkout, `pip install -e ".[dev]"`). Check with `cobol-parser --version`.
When only mockymock is installed (`uv tool install mocky-mock` puts
`mockymock` on the PATH but not its dependency's CLI), run every subcommand
below through it instead: `mockymock analyze <subcommand> <args>` forwards
the arguments to the same cobol-parser CLI unchanged.

Copybooks are the usual reason a run is incomplete. Pass `--copybook-path DIR`
(repeatable), or rely on a `cobol.yml` at the project root, which every
subcommand reads; `cobol-parser config` reports which file is in effect and
what it changed. In a file holding several `PROGRAM-ID`s, analyzers are
program-scoped: `--program NAME` picks one (default: the outermost).

## Which subcommand answers which question

| Question | Command |
|---|---|
| What is in this program, structurally? | `parse FILE` (AST JSON), `--stats` for counts |
| Everything wrong with it, one pass | `lint FILE [--format text]` |
| Where is this symbol declared and used? | `xref FILE` |
| What calls what, across the checkout? | `codebase-graph PATH... [--format mermaid]` |
| Who copies this copybook? | `copybook-impact MEMBER PATH...` |
| Control flow, PERFORM/GO TO/CALL | `program-flow FILE` |
| Is this paragraph reachable? | `dead-code FILE` |
| Is this field ever used? | `unused-variables FILE` |
| What business rules does it implement? | `business-rules FILE [--format text]` |
| Where does this field's value come from / go? | `lineage FILE --field NAME` |
| What breaks if I change this field, across programs and JCL? | `field-impact FIELD PATH... [--jcl JOB.jcl]` |
| How bad is this program / this estate? | `health FILE`, `scan --glob 'src/**/*.cbl'` |
| Duplicate code across programs | `scan --glob '**/*.cbl' --clones` |
| Byte offsets, lengths, REDEFINES, level-88s | `data-items FILE` |
| What does this record image say? | `decode DATA --copybook X.cpy` |
| Do two output files match, field by field? | `compare EXPECTED ACTUAL --copybook X.cpy [--key FIELD]` |
| Synthetic test rows from a layout | `gen-data X.cpy --rows N --seed N` |
| Test fixtures for a whole program | `gen-fixtures FILE --scenarios all` |
| What interface does this callee expose? | `program-signature FILE` |
| Do the CALLs match their callees' USING lists? | `call-check PATH... [--format text]` |
| What breaks if this field gets a bigger PICTURE? | `widen-check FIELD PATH... --to '9(9)'` |
| Do host variables match the DCLGEN? | `dclgen-check FILE` |
| SQLCODE/RESP unchecked, dynamic SQL | `sql-cics-check FILE` |
| What changed between two versions? | `diff OLD.cbl NEW.cbl` |
| What does this JCL run, on what data? | `jcl JOB.jcl --bindings` |
| What does `CALL "CEEDAYS"` need? | `le-info CEEDAYS` |

`lint` runs 34 rules over **one** parse — prefer it to running `dead-code`,
`unused-variables`, `move-type-check`, `io-sequence`, `linkage-check`,
`recursion-check`, `complexity`, `dclgen-check` and `sql-cics-check`
separately. Its seven bug-pattern rules have no subcommand of their own:
`truncation`, `subscript-range`, `next-sentence`, `perform-range`,
`file-status`, `uninitialized` and `obsolete-verb`; nor do its ten checks for
what IBM's compiler rejects or warns about: `undefined-name`, `value-clause`,
`data-layout`, `comparison`, `search-table`, `divide-by-zero`,
`subscript-usage`, `procedure-structure`, `corresponding` and
`arithmetic-operand`; nor do its eight code-pattern rules, taken from other
COBOL linters: `constant-condition`, `duplicate-branch`, `self-assignment`,
`stop-run-in-subprogram`, `string-pointer`, `loop-variable`, `evaluate-other`
and `nesting-depth` (the last two are info). `lint --callee-path DIR`
adds `call-check` (each CALL against the callee's USING). `scan` runs
analyzers over many files **in one process**, with per-file fault isolation —
prefer it to looping the CLI over a directory. It takes file paths, a
`--glob PATTERN` (repeatable) or `--files-from LIST`, not a bare directory.
With `--cache-dir DIR`, a rerun reuses the report of every file whose source
and copybooks are unchanged.

Every subcommand emits JSON by default (`--compact` to shrink, `-o FILE` to
write). `lint --format text` emits `file:line:column: severity [rule] message`.
`lint`, `call-check` and `scan` also take `--format sarif` (SARIF 2.1.0, for
code-scanning tools).

## Reading the output honestly

These reports are built to distinguish "this is false" from "I could not check
this," and that distinction is the point. Before asserting anything:

* Read **`caveats`**, **`unresolved`** and **`failed_rules`**. An unresolved
  `COPY` means "unused variable" findings are incomplete, not that the program
  is clean. Say so rather than silently reporting a partial answer as whole.
* Check **`warnings`** and **`errors`** on a parse. A program that parsed with
  errors yields analysis worth less than its confidence suggests.
* **Cite `file:line`** for every claim. Every finding carries a location, and
  with copybook expansion `lint` reports the file and line the finding *really*
  came from, not the expanded offset.

Exit codes are meaningful and differ by subcommand: `0` ran to completion
(findings alone never change it), `1` could not read/parse/write, `2` bad
arguments, or a file that was missing or failed to parse (`parse`, `batch`,
`scan`, `codebase-graph`, `copybook-impact`, `call-check`: the report is still
written, but incomplete), `3` a gate fired (`--fail-on` on `lint`,
`call-check` or `widen-check`; `jcl --strict`). Two exceptions: `compare`
exits `1` when the files differ (`2` for trouble), and `field-impact` and
`widen-check` exit `1` when the field matches nothing (`field-impact` still
prints the report). Never read a non-zero exit as "no findings".

## After editing COBOL

Column layout is load-bearing in fixed format: code lives in columns 8-72,
column 7 is the indicator, 73-80 are ignored. A statement pushed past column 72
silently loses its tail.

Re-run `lint` on the file you changed, and use `diff OLD NEW` to confirm the
change is the one intended — it compares structure, so it will not drown you in
reformatting noise the way `git diff` does on column-sensitive source.

## Do not

* Do not compute PICTURE arithmetic, byte offsets, COMP-3 sizes or EBCDIC
  encodings by hand. Use `data-items` and `decode`.
* Do not answer "is this used" by grepping the name — a reference can arrive
  through a copybook, a qualified `OF` name, a level-88 condition or a
  `THRU` range. Use `xref` or `unused-variables`.
* Do not summarize a program you have only partly read. Ask a subcommand.
