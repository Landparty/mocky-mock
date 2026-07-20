# FLOWMOCK — paragraph and section mocks

A small program whose driver performs a paragraph (`CALC-TOTALS`, which
makes a subprogram `CALL`) and a section (`RPT-BLOCK`, two paragraphs of
report arithmetic). The suite mocks those *internal flow targets*
directly — the first `.cut` feature that mocks something other than an
external boundary.

| Flow target | Entered by | Mocked by |
|-------------|-----------|-----------|
| Paragraph `CALC-TOTALS` | `PERFORM CALC-TOTALS` | `MOCK PARAGRAPH CALC-TOTALS` |
| Section `RPT-BLOCK` | `PERFORM RPT-BLOCK` | `MOCK SECTION RPT-BLOCK` |

Things this example demonstrates on purpose:

- **A flow mock swallows the boundaries inside it.** Case 1 mocks
  `CALC-TOTALS`, so the `CALL "RATECALC"` inside it is unreachable for
  that case and needs no `MOCK CALL` — the refusal gate knows the mock
  dispatch replaces the body. Case 2 runs the real paragraph, so there
  the CALL must be mocked, exactly as before.
- **Unmocked cases still run the real body.** Unlike a boundary mock's
  `WHEN OTHER` error trap, a flow mock's `WHEN OTHER` performs the
  relocated real body — one compiled binary serves cases that mock the
  target and cases that don't.
- **`VERIFY PARAGRAPH/SECTION ... WAS PERFORMED ...`** asserts on the
  tally (`UT-PARAGRAPH-CALC-TOTALS-TALLY` / `UT-SECTION-RPT-BLOCK-TALLY`),
  counting only entries through the target's own header.

Flow mocks are fail-closed: a target that is a `GO TO` target anywhere,
sits inside a `PERFORM ... THRU` range, belongs to a section that is
itself performed, is reached by GO-TO fall-through, or shares its header
line with code refuses (`UNSUPPORTED_FLOW_MOCK_TARGET`) rather than risk
running the dispatch and the real body back to back. Mind COBOL reserved
words when naming sections you plan to mock (`REPORTING`, for example,
is reserved — this example's section is `RPT-BLOCK` for that reason).

Run it:

```bash
mockymock run examples/flowmock/FLOWMOCK.cbl --cut examples/flowmock/FLOWMOCK.cut
```
