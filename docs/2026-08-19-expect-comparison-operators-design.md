# EXPECT negation and comparison operators

**Date:** 2026-08-19
**Status:** Implemented

## Problem

`EXPECT <data-name> TO BE <value>` asserted exact equality only. Real
assertions frequently need "anything but this value" (a status field
that must not be an error code) or a threshold (a computed total that
must exceed zero, a rate capped at a maximum). Authors worked around it
by asserting one exact expected value, which over-pins tests to
incidental byte-exact output.

## Design

### Grammar

```
EXPECT <data-name> [NOT] TO BE [GREATER THAN|LESS THAN [OR EQUAL TO]] <value>
```

Ten phrases total: five relations (`TO BE`, `TO BE GREATER THAN`,
`TO BE LESS THAN`, `TO BE GREATER THAN OR EQUAL TO`,
`TO BE LESS THAN OR EQUAL TO`), each negatable with a leading `NOT`.
Phrase words are case-sensitive uppercase, like every other DSL keyword.

### Model

`ExpectDirective` gains `operator: str = "="` — the canonical COBOL
relation spelling (`model.EXPECT_OPERATORS`: `=`, `NOT =`, `>`, `NOT >`,
`<`, `NOT <`, `>=`, `NOT >=`, `<=`, `NOT <=`). The default keeps every
hand-built directive and every pre-operator `.cut` file byte-identical
in behavior — plain `TO BE` still means exact equality and still
compiles to exactly the same generated COBOL.

The parser normalizes the phrase to the operator (`_expect_operator`);
downstream consumers never re-parse English. PROVIDER row expansion
copies the operator through unchanged (`{Placeholder}` substitution
applies to the value only, as before).

### Codegen (splicer/driver.py)

The generated `IF` guards the *failure* branch, so each operator
compiles to its negation via `_EXPECT_FAIL_CONDITIONS`:

| Asserted | Emitted IF |
|---|---|
| `=` | `NOT =` |
| `NOT =` | `=` |
| `>` / `<` | `NOT >` / `NOT <` |
| `NOT >` / `NOT <` | `>` / `<` |
| `>=` / `<=` | `<` / `>` |
| `NOT >=` / `NOT <=` | `>=` / `<=` |

`>=`/`<=` negate to the equivalent plain relation rather than a
NOT-prefixed compound, keeping every emitted condition a simple COBOL-85
relational form. An operator outside the map raises `ValueError` in
codegen (same posture as `_verify_condition`); the parser is the real
gate, so this is a should-be-unreachable invariant for `.cut`-sourced
suites.

The FAIL `DISPLAY` echoes the asserted operator between name and value
(`expected WS-X > 5, got ...`) — for `=` this is byte-identical to the
pre-operator message.

### Report attribution (report/json_report.py)

`_attribute_failure` previously split the EXPECT head on the first
`" = "`. It now matches `_EXPECT_HEAD_RE` (name, operator, expected),
with compound operator alternatives ordered before their prefixes so
`NOT >=` never mis-splits as `NOT >`. The JSON `expected` field keeps
the bare value for `=` (existing consumers see no change) and is
operator-prefixed otherwise (`"> 5"`, `"NOT = 0"`) so the field stays
self-describing.

### Fail-closed parsing

A malformed phrase would otherwise fall into the value capture and
splice verbatim into the generated IF, surfacing as a cobc compile error
pointing at generated code. `_EXPECT_DANGLING_PHRASE_RE` refuses a value
starting with a whole comparison-phrase word (`GREATER`, `LESS`, `THAN`,
`OR`, `EQUAL` followed by whitespace/end) with a line-numbered
`CutParseError` naming the supported phrases. Hyphenated identifiers
(`GREATER-VALUE`) and quoted literals are unaffected.

## Rejected alternatives

- **Symbolic operators (`EXPECT WS-X >= 5`).** The DSL is consistently
  English-phrase shaped (`WAS CALLED AT LEAST ONCE`, `FILE-STATUS IS`);
  a second symbolic spelling of the same thing doubles the grammar
  surface without adding capability. The canonical symbols live on the
  model only.
- **Negation as a boolean flag on `ExpectDirective`.** Two fields
  (`operator` + `negated`) push the combination logic into every
  consumer; one canonical operator string keeps driver/report lookups a
  flat map.
- **`TO BE AT LEAST` / `AT MOST` synonyms.** Redundant with
  `GREATER/LESS THAN OR EQUAL TO`; synonyms multiply the phrase table
  and the failure-message vocabulary without new expressive power.
- **Range assertion (`TO BE BETWEEN a AND b`).** Composable from two
  EXPECT lines on the same field; not worth a three-operand grammar
  shape in v1.
