"""`mockymock init`: generate --with-data + run --record-expectations in one."""

from __future__ import annotations

import argparse
from pathlib import Path

from mockymock._lines import read_utf8_source
from mockymock.cli._args import _suite_name
from mockymock.cli._common import (
    _check_input_files,
    _default_output,
    _distinct_case_count,
    _warn_asserting_nothing,
)
from mockymock.cli.commands.generate import _cmd_generate
from mockymock.cli.commands.run import _cmd_run


def _cmd_init(args: argparse.Namespace) -> int:
    """`mockymock init PROG.cbl`: compose the existing `generate
    --with-data` + `run --record-expectations` path into one command, so
    a first scaffold has real, golden-recorded assertions instead of
    empty mock bodies -- and degrade honestly (no Docker attempt, a
    clear next step) when Docker isn't set up yet. See
    docs/2026-09-15-init-command-design.md.

    Reentrant rather than a deep refactor of `_cmd_generate`/`_cmd_run`'s
    internals: builds real argv lists and parses them with the CLI's
    own `build_parser()` (mockymock.cli.parser), so every flag `generate --with-data`/
    `run --record-expectations` would need gets argparse's own correct
    default -- never a hand-built Namespace that could silently miss an
    attribute those large functions read. This is a deliberate departure
    from the design doc's proposed 'refactor into a plain function
    returning a result object' approach: lower risk for the same
    external behavior, since neither _cmd_generate nor _cmd_run's
    existing code changes at all."""
    from mockymock.cli.doctor import gather_full_status

    # The one call back into the parser: it imports this module to add
    # `init`'s own subparser, so build_parser is imported at call time only.
    from mockymock.cli.parser import build_parser
    from mockymock.runtime.status import OK

    source_path = Path(args.program)
    if not _check_input_files("mockymock init", source_path):
        return 1

    output_path = _default_output(args, source_path)
    if source_path.suffix.lower() == ".cut" or output_path.resolve() == (
        source_path.resolve()
    ):
        # `mockymock init X.cut` would otherwise be told X.cut "already
        # exists, pass --force" -- and --force would then parse the .cut
        # as COBOL and overwrite it with the result.
        print(
            f"mockymock init: {source_path} is the .cut file, not the COBOL "
            f"program -- pass the program (e.g. "
            f"{source_path.with_suffix('.cbl')})"
        )
        return 1
    if output_path.exists() and not args.force:
        print(
            f"mockymock init: {output_path} already exists -- pass --force "
            f"to overwrite it, or --output to write somewhere else"
        )
        return 1

    config = getattr(args, "_config", None)
    copybook_paths = args.copybook_path or []
    extra_copybook_paths = args.extra_copybook_path or []

    generate_argv = [
        "generate",
        str(source_path),
        "--output",
        str(output_path),
        "--with-data",
        "--scenarios",
        args.scenarios,
    ]
    if args.force:
        # Already gated above with init's own message; generate refuses
        # an existing output without it.
        generate_argv.append("--force")
    if args.seed is not None:
        generate_argv += ["--seed", str(args.seed)]
    for path in copybook_paths:
        generate_argv += ["--copybook-path", path]
    for path in extra_copybook_paths:
        generate_argv += ["--extra-copybook-path", path]

    print(f"mockymock init: scaffolding {output_path} from {source_path} (--with-data)")
    generate_args = build_parser().parse_args(generate_argv)
    generate_args._config = config
    exit_code = _cmd_generate(generate_args)
    if exit_code != 0:
        return exit_code

    if args.scenarios != "happy":
        print(
            "Note: branch-targeted scenarios are not yet verified to reach "
            "their named arm -- see "
            "docs/2026-09-04-scenario-branch-verification.md. Confirm with "
            "'mockymock run ... --trace' for anything security- or "
            "correctness-critical."
        )

    # Gate on the Docker daemon alone (mocky-mock-vscode#103): a toolchain
    # image or container that isn't built yet is what `run` builds on
    # demand (`ensure_toolchain`), so a fresh install with Docker running
    # used to skip recording and say Docker wasn't available.
    report = gather_full_status()
    daemon = next((c for c in report.toolchain.checks if c.id == "daemon"), None)
    docker_up = daemon.state == OK if daemon is not None else report.ready
    if not docker_up:
        print(
            "mockymock init: Docker isn't available, so I generated a "
            "suite with real test data but could not run it to record "
            f"expected values. Run 'mockymock run {source_path} --cut "
            f"{output_path} --record-expectations' once Docker is set up "
            "(see 'mockymock doctor')."
        )
        return 0

    run_argv = [
        "run",
        str(source_path),
        "--cut",
        str(output_path),
        "--record-expectations",
    ]
    for path in copybook_paths:
        run_argv += ["--copybook-path", path]
    for path in extra_copybook_paths:
        run_argv += ["--extra-copybook-path", path]

    if not report.ready:
        print(
            "mockymock init: the GnuCOBOL toolchain isn't set up yet -- "
            "building it first (one time; this can take a few minutes)"
        )
    print(f"mockymock init: running {output_path} to record expected values")
    run_args = build_parser().parse_args(run_argv)
    run_args._config = config
    run_exit_code = _cmd_run(run_args)
    if run_exit_code == 0:
        # Recording can leave a case with nothing to assert (a program
        # whose result the scaffold could not see, issue #275): such a
        # suite passes whatever the program does, so it is not "done".
        cut_text = read_utf8_source(output_path)
        case_count = _distinct_case_count(cut_text)
        empty = _warn_asserting_nothing("init", cut_text, stubs_count=False)
        if case_count and empty == case_count:
            print(
                f"mockymock init: {output_path} was written, but none of its "
                f"test cases asserts anything -- add an EXPECT on what the "
                f"program writes before relying on it"
            )
            return 1
        print(
            f"mockymock init: next, run 'mockymock run {source_path} "
            f"--cut {output_path}'"
        )
    else:
        print(
            f"mockymock init: {output_path} was written, but recording its "
            f"expected values failed (see above) -- fix that, then run "
            f"'mockymock run {source_path} --cut {output_path} "
            f"--record-expectations'"
        )
    return run_exit_code


def register_init(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock init` to the top-level parser."""
    init_parser = subparsers.add_parser(
        "init",
        help=(
            "One command from a COBOL program to a .cut file with real, "
            "golden-recorded assertions"
        ),
        description=(
            "Composes 'generate --with-data' + 'run --record-expectations' "
            "into one step, so a first scaffold has real generated data "
            "and recorded expected values instead of empty mock bodies. "
            "Degrades to a plain data-driven scaffold (no run attempted) "
            "with a clear next step when Docker isn't set up yet. See "
            "docs/2026-09-15-init-command-design.md."
        ),
    )
    init_parser.add_argument("program")
    init_parser.add_argument(
        "-o",
        "--output",
        help="Where to write the .cut file (default: tests/<folder>/<program>.cut)",
    )
    init_parser.add_argument(
        "--name",
        type=_suite_name,
        help="Name a second suite for the program: writes <program>.<NAME>.cut",
    )
    init_parser.add_argument(
        "--seed", type=int, help="Seed for the fixture bundle's random data generation"
    )
    init_parser.add_argument(
        "--scenarios",
        choices=["happy", "branches", "all"],
        default="happy",
        help="Scenario strategy for the fixture bundle (default happy)",
    )
    init_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    init_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output .cut file if it already exists",
    )
    init_parser.set_defaults(func=_cmd_init)
