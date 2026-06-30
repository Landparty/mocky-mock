# mockymock

Mocks static `CALL` statements in a COBOL program, compiles the instrumented
copy with GnuCOBOL, runs it, and reports pass/fail.

See `docs/2026-06-30-mockymock-mvp-design.md` for the design and
`docs/2026-06-30-mockymock-mvp-plan.md` for the implementation plan this
repo was built from.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
mockymock setup           # installs GnuCOBOL if not already on PATH
python -m pytest tests/unit -v
```

`tests/integration/` additionally requires `cobc` on PATH and is skipped
automatically if it isn't found.
