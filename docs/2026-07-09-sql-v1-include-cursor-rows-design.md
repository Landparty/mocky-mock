# SQL v1: `EXEC SQL INCLUDE` host-variable copybooks + cursor `ROWS` sugar

Date: 2026-07-09
Status: proposed

## Motivation

mockymock already has substantial `EXEC SQL` support: `EXEC SQL INCLUDE SQLCA
END-EXEC` is exploded into a generated SQLCA group item
(`mockymock/splicer/sqlca.py`), and every `EXEC SQL ... END-EXEC` in the
PROCEDURE DIVISION — including cursor `DECLARE`/`OPEN`/`FETCH`/`CLOSE`, which
are all just `ExecSQLStatement` instances — is already spliced out by the
generic boundary-mocking machinery (`MOCK SQL "<prefix>"` matches become mock
bodies; unmatched sites become a hard-fail trap).

The one concrete, confirmed gap (real-world-readiness audit, Finding 5;
`tests/unit/test_sqlca.py`) is `EXEC SQL INCLUDE <member> END-EXEC` for
anything **other than SQLCA** — a DCLGEN-style host-variable copybook, e.g.
`EXEC SQL INCLUDE CUSTREC END-EXEC` — which today refuses the whole program
(`UNSUPPORTED_DATA_DIVISION_EXEC`). Without it, a program's SQL host
variables never exist as real data items, so no mock body can `MOVE` a value
into them — cursor-based DB2 programs are blocked before mocking is even a
question.

Once host variables exist, cursor FETCH loops are already mockable today via
a hand-written `MOCK SQL "FETCH ..."` body that manually inspects the
existing per-mock tally field and sets `SQLCODE`. This design adds a second,
smaller piece: `ROWS` sugar that generates that boilerplate instead of
requiring it hand-written.

## Scope

1. Resolve `EXEC SQL INCLUDE <member> END-EXEC` (non-SQLCA) via the existing
   `--copybook-path` mechanism, exposing host variables as real WORKING-STORAGE
   data items.
2. Add `MOCK SQL "<prefix>" ROWS ( ... ) ( ... ) END-MOCK` DSL sugar for
   canned cursor-FETCH row sequences.

Out of scope for this round (deferred, not designed further here):
- Nested `EXEC SQL INCLUDE` (a resolved copybook that itself contains another
  *live* `EXEC SQL INCLUDE`) — refused, not resolved.
- Overriding the terminal/exhaustion `SQLCODE` in a `ROWS` block — fixed at
  100.
- Generalizing `ROWS` sugar to non-SQL categories (e.g. `READ`) — `READ`
  already has its own tally-driven EOF idiom (see README).

## Component 1: `EXEC SQL INCLUDE <member>` resolution

**Where:** `mockymock/splicer/sqlca.py` (`transform_data_division_exec`,
`_handle_block`), and its two call sites in `mockymock/cli/main.py`
(`_cmd_generate`, `_cmd_run`).

**Signature change:** `transform_data_division_exec(lines, copybook_paths:
list[str] | None = None)`. Both CLI call sites pass `args.copybook_path`
(the same flag already used for plain `COPY` expansion — no new flag).

**Resolution (revised after a spike — see below):** `find_copybook_file` /
`CopybookSearchPath` turned out to live in `cobolparser/preprocess/path_resolver.py`
/ `models.py`, which are **not** in `cobolparser/preprocess/__init__.py`'s
`__all__` — not the declared public surface, and not something
`interface-contract.md` should pin. Instead, resolution goes through the
same public `expand_copybooks` plain `COPY` already uses: build a synthetic
one-line snippet `"       COPY <member>."` and call
`expand_copybooks(snippet, copybook_paths=...)`. Spiked directly (not just
reasoned about): this resolves the member and inlines its content
(including a DCLGEN-style embedded `EXEC SQL DECLARE ... TABLE ... END-EXEC`
stanza, verbatim) into `.expanded_source`; an unresolvable member raises
`cobolparser.preprocess.CopybookNotFoundError` (which *is* in `__all__`) —
caught and turned into the same `UNRESOLVED_COPYBOOK` refusal. This gets
path-traversal protection, nested-`COPY` handling, and size/encoding checks
for free, and guarantees INCLUDE resolves exactly the way COPY does (same
extensions, same case rules) since it's the literal same code path — not a
reimplementation that could quietly diverge.

On success, `.expanded_source` is *not yet* normalized (`expand_copybooks`
runs pre-normalize in the existing pipeline; `transform_data_division_exec`
runs post-normalize), so it's run through `normalize_fixed_format` in
isolation before splicing — spiked and confirmed this produces clean
free-form lines from the resolved content. The normalized lines replace the
`EXEC SQL INCLUDE ... END-EXEC` block, preceded by a `*>` marker comment
(mirroring the existing SQLCA-replacement marker in the same module).

**Re-scan for embedded declaratives:** after splicing, the scan index is
*not* advanced past the newly-inserted lines — `transform_data_division_exec`'s
existing `while` loop keeps scanning them. A DCLGEN copybook always emits its
own `EXEC SQL DECLARE <table> TABLE (...) END-EXEC` immediately before the
host-variable record; this re-scan lets the *already-existing* DECLARE-TABLE
branch comment it out with no new recursion code.

**Nested INCLUDE:** while re-scanning spliced-in content, a second *live*
`EXEC SQL INCLUDE` is refused (`UNSUPPORTED_DATA_DIVISION_EXEC`, message
naming it as a nested INCLUDE) rather than resolved — tracked via a simple
"currently inside spliced INCLUDE content" flag during the scan.

**Failure path:** no `--copybook-path` given, or the member can't be found →
`RefusalReason(code="UNRESOLVED_COPYBOOK", ...)`. Deliberately the *same*
code plain unresolved `COPY` already uses (`analysis/refusal.py`
`check_unresolved_copybooks`), not a new one — same fix, same message shape,
regardless of which mechanism pulled the copybook in.

## Component 2: `MOCK SQL "<prefix>" ROWS` cursor sugar

**Grammar** (`mockymock/dsl/parser.py`, `mockymock/dsl/model.py`): the
existing `MOCK SQL "<prefix>"` opening line gains an optional trailing
`ROWS` keyword. In `ROWS` mode, each subsequent line up to `END-MOCK` must
match `( FIELD = value, FIELD = value, ... )` — one row per line — instead
of the free-form COBOL text `MOCK` bodies collect today.

`MockDirective` gains `rows: list[list[tuple[str, str]]] | None`, populated
instead of `body_lines` — the two are mutually exclusive; a `ROWS` mock
cannot also carry hand-written statements. Value syntax is unparsed free
text, matching the existing `EXPECT ... TO BE <value>` convention: whatever
the author writes (`"SMITH"`, `100`) is spliced verbatim into the generated
`MOVE`.

**Codegen (splice time, not parse time):** the tally field name isn't known
until `naming.TallyRegistry` resolves it (post-parse, whole-suite scoped), so
expansion happens wherever `body_lines` are currently spliced in for a
`MockDirective`. A `rows`-bearing directive instead generates:

```cobol
EVALUATE TRUE
    WHEN UT-SQL-FETCH-EMP-CURSOR-TALLY = 1
        MOVE "SMITH" TO EMP-NAME
        MOVE 100 TO EMP-ID
        MOVE 0 TO SQLCODE
    WHEN UT-SQL-FETCH-EMP-CURSOR-TALLY = 2
        MOVE "JONES" TO EMP-NAME
        MOVE 101 TO EMP-ID
        MOVE 0 TO SQLCODE
    WHEN OTHER
        MOVE 100 TO SQLCODE
END-EVALUATE
```

using the tally field name already resolved for this (SQL, key) pair — no
new naming logic. Exhaustion is always `SQLCODE 100` (DB2's real "not found"
code) on `WHEN OTHER`.

**Refusal:** malformed `ROWS` syntax (unbalanced parens, missing `=`, empty
block) is a DSL parse error (`CutParseError`), the same tier as today's other
`.cut` syntax errors — not a new refusal code.

## Error handling summary

| Condition | Code |
|---|---|
| `EXEC SQL INCLUDE <member>` (non-SQLCA), no `--copybook-path` or member not found | `UNRESOLVED_COPYBOOK` (existing code, reused) |
| `EXEC SQL INCLUDE <member>` nested inside a resolved INCLUDE's own content | `UNSUPPORTED_DATA_DIVISION_EXEC` (existing code, new trigger) |
| Malformed `ROWS` block syntax | `CutParseError` (existing DSL error path) |

No new refusal codes are introduced.

## Testing

- Unit (`tests/unit/test_sqlca.py`): resolved non-SQLCA `INCLUDE` splices
  file content in place; embedded `DECLARE TABLE` inside the spliced content
  is commented out; nested live `INCLUDE` inside spliced content refuses;
  missing member / no `--copybook-path` refuses `UNRESOLVED_COPYBOOK`.
- Unit (`tests/unit/test_dsl_parser_v2.py` or similar): `ROWS` grammar
  round-trips; malformed row syntax raises `CutParseError`; `rows` and
  `body_lines` remain mutually exclusive.
- Unit (naming/injector/generator tests, wherever `body_lines` splicing is
  covered today): `rows`-bearing directive codegens the expected
  `EVALUATE`/`WHEN <tally> = N`/`WHEN OTHER` shape using the resolved tally
  field name.
- Integration (Docker): a DCLGEN-shaped fixture — `EXEC SQL INCLUDE` copybook
  containing an embedded `DECLARE TABLE` plus a host-variable record, a
  `DECLARE CURSOR`/`OPEN`/`FETCH`/`CLOSE` loop in the PROCEDURE DIVISION, and
  a `.cut` using `MOCK SQL "FETCH ..." ROWS` — compiled and run end-to-end
  through GnuCOBOL, asserting the loop consumes exactly the row count given
  and the program's own EOF/loop-exit logic (driven by `SQLCODE`) behaves
  correctly.
