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

- The Chocolatey GnuCOBOL package installs `cobc` under
  `C:\ProgramData\chocolatey\lib\gnucobol\tools` and sets `COB_CONFIG_DIR`
  as a **user** environment variable — open a fresh shell after installing,
  or a stale session's `cobc` will fail with
  `configuration error: default.conf: No such file or directory`.
- Windows Smart App Control / Application Control policies can
  intermittently refuse to launch the freshly compiled unsigned test binary
  (`WinError 4551`). mockymock reports this as a clean run failure; the fix
  is an OS-policy exclusion for the sandbox/temp directory, not a code
  change.
