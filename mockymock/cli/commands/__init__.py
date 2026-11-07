"""One module per `mockymock` subcommand (or tight family of them).

Each exposes its `_cmd_*` entry point(s); `mockymock.cli.main` imports
them into `build_parser()`. Modules here import from
`mockymock.cli._common` and each other, never from `mockymock.cli.main`
at import time (`init`'s call-time import of `build_parser` is the one
exception, documented there).
"""
