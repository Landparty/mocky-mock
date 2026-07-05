# mockymock

Mocks static `CALL` statements in a COBOL program, compiles the instrumented
copy with GnuCOBOL, runs it, and reports pass/fail.

See `docs/2026-06-30-mockymock-mvp-design.md` for the design and
`docs/2026-06-30-mockymock-mvp-plan.md` for the implementation plan this
repo was built from.

## Setup

Requires a running Docker daemon (Docker Desktop on Windows/macOS). COBOL
is compiled and executed inside a GnuCOBOL container — nothing runs on the
host, and no local GnuCOBOL install is needed.

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
mockymock setup           # builds the GnuCOBOL image, starts mockymock-cobc
python -m pytest tests/unit -v
```

`tests/integration/` additionally requires the Docker daemon to be
reachable and is skipped automatically if it isn't. `mockymock run` brings
the container up on its own, so `mockymock setup` is optional.

### Windows notes

On Windows, ensure Docker Desktop is running before invoking `mockymock setup` or
`mockymock run`. COBOL compilation and execution happen entirely inside the container.
