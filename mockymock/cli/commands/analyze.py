"""`mockymock analyze`: pass-through to cobol-parser's analysis CLI."""

from __future__ import annotations

import argparse
import sys


def _cmd_analyze(args: argparse.Namespace) -> int:
    # cobolparser.cli.parse.main() takes no argv parameter -- unlike
    # mockymock.cli.main.main(), it reads sys.argv[1:] directly. Patching it here
    # (restored in `finally`) is the standard idiom for delegating to an
    # argparse CLI that doesn't accept argv; safe in this single-threaded,
    # sequential-CLI context. The isinstance check (rather than `exc.code or
    # 0`) is required for mypy: SystemExit.code is typed `int | str | None`,
    # and this function's return type is `int`.
    from cobolparser.cli.parse import main as cobolparser_main

    saved_argv = sys.argv
    sys.argv = ["cobol-parser", *args.cobolparser_args]
    try:
        cobolparser_main()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.argv = saved_argv
    return 0
