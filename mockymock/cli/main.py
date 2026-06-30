"""mockymock CLI entry point."""

from __future__ import annotations

import argparse
import sys

from mockymock import __version__


def _cmd_setup(args: argparse.Namespace) -> int:
    from mockymock.runtime.gnucobol_bootstrap import (
        GnuCobolNotFoundError,
        bootstrap,
    )

    try:
        info = bootstrap()
    except GnuCobolNotFoundError as exc:
        print(f"mockymock setup: {exc}")
        return 1
    print(f"mockymock setup: found cobc at {info.path} ({info.version})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mockymock")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser(
        "setup", help="Detect or install GnuCOBOL (cobc)"
    )
    setup_parser.set_defaults(func=_cmd_setup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
