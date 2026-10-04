# Verification levels

`mockymock report` gives every test case the highest level it reaches, in
order. A level is only reached if every level below it is.

| Level | Name | The case... | How to reach it |
|---|---|---|---|
| — | Refused | belongs to a suite the static gate refuses | Fix what `mockymock lint` prints (`mockymock explain <CODE>`). |
| L0 | Static | passes the refusal gate: every reachable CALL, file op, SQL, CICS, DL/I and ACCEPT is mocked, so nothing escapes | `mockymock lint` clean. |
| L1 | Executed | passed in a real GnuCOBOL compile and run | `mockymock run` (needs Docker). |
| L2 | Strong | asserts at least one thing, and the whole suite's mutation score is at or above the threshold (default 80%, `--mutation-threshold`) | `mockymock mutate`; kill survivors by adding the assertion each one names. |
| L3 | Dialect-checked | reaches no high/medium GnuCOBOL vs IBM COBOL risk from its PERFORM target | Nothing to fix in the test: the risk is in the program. Either accept L2 and say the case is GnuCOBOL-proven only, or confirm it on z/OS (L4). |
| L4 | Mainframe-confirmed | ran on z/OS with the same mocks | Not computed by the report. `mockymock export PROGRAM.cbl --cut PROGRAM.cut` writes source a z/OS compiler accepts; running it there is the developer's call. |

## Dialect risks that block L3

GnuCOBOL (`-std=mvs`) is a real compiler and the right everyday oracle,
but not IBM Enterprise COBOL. The report flags these per statement:

| Code | Severity | Why |
|---|---|---|
| `HEX_LITERAL` | high | `X'C1'` is `A` in EBCDIC, not in ASCII. |
| `EBCDIC_COLLATION` | medium | `<`/`>` on alphanumeric data: EBCDIC orders lowercase < uppercase < digits, ASCII the reverse. |
| `SORT_COLLATION`, `SEARCH_ALL_COLLATION` | medium | Key order follows the native collating sequence. |
| `SIGN_OVERPUNCH` | medium | MOVE between signed zoned decimal and alphanumeric: the overpunched sign byte differs. |
| `INTERMEDIATE_PRECISION` | medium | Division/exponentiation: intermediate sizing differs, so trailing digits or ROUNDED can differ. |
| `CLOCK_DEPENDENT` | medium | `FUNCTION CURRENT-DATE`, `WHEN-COMPILED`, `RANDOM`: not repeatable unless the test pins it. |
| `BINARY_TRUNCATION` | low | COMP/BINARY overflow depends on the shop's TRUNC option. |
| `NUMERIC_EDITED` | low | Small differences in edited output. |
| `INTRINSIC` | low | Implementation-defined corner cases. |

The check is heuristic and says so: an operand whose PICTURE it cannot
resolve is not flagged. When reporting, name the risk and the line, not
just the level ("L2: reaches the COMPUTE at line 212, which divides").

## Talking about levels

Quote what the report computed. "9 tests pass" is L1. "The suite catches
91% of injected faults" is what makes it L2. Never describe an L1 suite as
"thoroughly tested".
