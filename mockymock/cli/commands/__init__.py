"""One module per `mockymock` subcommand (or tight family of them).

Each exposes its `_cmd_*` handler(s) and, next to each, the
`register_<name>(subparsers)` that adds its subparser and flags;
`mockymock.cli.parser.build_parser()` calls them in help order. Modules
here import from `mockymock.cli._common`, `mockymock.cli._args` and each
other, never from `mockymock.cli.main` or `mockymock.cli.parser` at import
time (`init`'s call-time import of `build_parser` and `job`'s of `main`
are the exceptions, documented there).
"""
