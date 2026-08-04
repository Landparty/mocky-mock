# fixtures/FIXTUREDEMO — the gen-fixtures worked example

The end-to-end worked example for the cross-repo `gen-fixtures`
program-scoped test-data initiative (Phase 9 of `Landparty/cobol-parser`'s
`docs/plans/2026-08-02-program-data-generation-implementation.md`):
`FIXTUREDEMO.cbl` and `FIXTUREDEMO.bundle.json` are copied verbatim from
that repo's own `examples/fixtures/` (see its own README there for the
program walkthrough and the boundary/category table); `FIXTUREDEMO.cut`
is generated here, from that exact bundle, and checked in as this repo's
own golden.

Unlike [`examples/custprog/`](../custprog/) (which deliberately
demonstrates a known DCLGEN `EXEC SQL INCLUDE` gap), every boundary here
resolves cleanly — this is the clean end-to-end reference, not an edge
case.

## Regenerating

```bash
mockymock generate examples/fixtures/FIXTUREDEMO.cbl \
    --fixtures examples/fixtures/FIXTUREDEMO.bundle.json \
    -o examples/fixtures/FIXTUREDEMO.cut
```

Deliberately uses `--fixtures` (a checked-in bundle JSON), not
`--with-data`: this example's `.cut` golden is pinned against the exact
bundle cobol-parser's own repo golden-tests, decoupled from whatever
cobol-parser commit `pyproject.toml` happens to have pinned at any given
moment. See [`tests/integration/test_fixturedemo_golden.py`](../../tests/integration/test_fixturedemo_golden.py)
for the byte-identical regeneration check, the lint-clean check, and the
Docker-gated real run.

If `FIXTUREDEMO.cbl`/`FIXTUREDEMO.bundle.json` change upstream in
cobol-parser, re-copy both files here and regenerate `FIXTUREDEMO.cut` in
the same change.

Run it:

```bash
mockymock run examples/fixtures/FIXTUREDEMO.cbl --cut examples/fixtures/FIXTUREDEMO.cut
mockymock lint examples/fixtures/FIXTUREDEMO.cbl --cut examples/fixtures/FIXTUREDEMO.cut
```
