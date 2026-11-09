"""`mockymock skills install|plugin|mode`."""

from __future__ import annotations

import argparse
from pathlib import Path


def _cmd_skills_install(args: argparse.Namespace) -> int:
    """Copy the packaged agent skills (mockymock, cobol-analysis,
    cobol-test, mockymock-setup) into the skills directory of Claude Code
    and/or GitHub Copilot (--target; skills_cmd.resolve_target names the directories),
    under the home directory or, with --project, the current one. Pure file copy -- no Docker, no config. Fail-closed
    across the set: if any target exists and --force is absent, nothing is
    written, so a half-installed set never mixes old and new copies."""
    from mockymock.cli.skills_cmd import (
        SKILL_NAMES,
        TARGET_LABELS,
        TARGETS,
        SkillTargetExistsError,
        install_skill,
        resolve_target,
    )

    names = args.skill or list(SKILL_NAMES)
    unknown = [n for n in names if n not in SKILL_NAMES]
    if unknown:
        print(
            f"mockymock skills install: unknown skill(s) {', '.join(unknown)} "
            f"(expected: {', '.join(SKILL_NAMES)})"
        )
        return 1
    assistants = list(TARGETS) if args.target == "all" else [args.target]
    targets = [
        (name, resolve_target(args.project, name, assistant))
        for assistant in assistants
        for name in names
    ]
    if not args.force:
        occupied = [t for _, t in targets if t.exists() or t.is_symlink()]
        if occupied:
            for target in occupied:
                print(
                    f"mockymock skills install: {target} already exists; "
                    f"use --force to overwrite"
                )
            return 1
    for name, target in targets:
        try:
            install_skill(target, force=args.force, name=name)
        except SkillTargetExistsError as exc:
            print(f"mockymock skills install: {exc}")
            return 1
        print(f"mockymock skills install: installed -> {target}")
    tools = " / ".join(TARGET_LABELS[a] for a in assistants)
    print(
        f"mockymock skills install: start a new {tools} session to pick up "
        "the skills; ask it to set up this repository for mockymock "
        "(mockymock-setup), or to test a COBOL program (cobol-test)."
    )
    return 0


def _cmd_skills_plugin(args: argparse.Namespace) -> int:
    """Write the cobol-testing Claude Code plugin as a local marketplace
    (no clone, no network), for `/plugin marketplace add <dir>`."""
    from mockymock import __version__
    from mockymock.cli.skills_cmd import (
        LOCAL_MARKETPLACE_NAME,
        PLUGIN_NAME,
        PluginTargetError,
        default_plugin_dir,
        export_plugin,
    )

    target = (
        Path(args.directory).expanduser() if args.directory else default_plugin_dir()
    )
    target = target.resolve()
    try:
        plugin_dir = export_plugin(target, version=__version__, force=args.force)
    except PluginTargetError as exc:
        print(f"mockymock skills plugin: {exc}")
        return 1
    print(f"mockymock skills plugin: wrote {PLUGIN_NAME} {__version__} -> {target}")
    print("mockymock skills plugin: in Claude Code, run:")
    print(f"  /plugin marketplace add {target}")
    print(f"  /plugin install {PLUGIN_NAME}@{LOCAL_MARKETPLACE_NAME}")
    print(
        "mockymock skills plugin: or load it for one session with "
        f"`claude --plugin-dir {plugin_dir}`. Re-run with --force after "
        "upgrading mockymock, then `/plugin marketplace update "
        f"{LOCAL_MARKETPLACE_NAME}`."
    )
    return 0


def _cmd_skills_mode(args: argparse.Namespace) -> int:
    """Read back (or set) the project's AI assistant mode -- how much the
    packaged skill checks in with the developer while it builds a suite.
    Loads the config file itself rather than using `args._config`: `skills`
    is one of the subcommands `main()` deliberately lets run with a
    malformed config (it defines neither `copybook_path` nor `seed`), and
    this is the one `skills` leaf that actually reads it, so it reports
    the parse error itself the same way `doctor` does."""
    from mockymock.project.ai_mode import (
        ModeError,
        format_mode_json,
        format_mode_report,
        resolve_mode,
        validate,
        write_mode,
    )
    from mockymock.project.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"mockymock skills mode: {exc}")
        return 1

    if args.set is not None:
        try:
            # Validated before the write so a typo'd mode names the valid
            # set instead of landing in the file for the next `run` to
            # reject. `choices=` would do this in argparse, but that needs
            # MODES imported at parser-build time -- see the deferred-import
            # rule in .okf/cli.md's Gotchas.
            validate(args.set)
            written = write_mode(args.set, config)
        except ModeError as exc:
            print(f"mockymock skills mode: {exc}")
            return 1
        try:
            config = load_config()
        except ConfigError as exc:
            print(
                f"mockymock skills mode: wrote {written}, but it no longer parses: {exc}"
            )
            return 1
        print(f"mockymock skills mode: {args.set} -> {written}")

    resolved = resolve_mode(config)
    if args.json:
        import json

        print(json.dumps(format_mode_json(resolved), indent=2))
    else:
        print(format_mode_report(resolved))
    return 0


def register_skills(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock skills` to the top-level parser."""
    skills_parser = subparsers.add_parser(
        "skills",
        help="Manage the packaged agent skills (Claude Code, GitHub Copilot)",
    )
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command")

    # Bare `mockymock skills` (no subcommand) must print THIS parser's
    # usage, not fall through to main()'s top-level-help fallback -- the
    # user typed a valid subcommand and needs its own options, not all
    # twelve commands (2026-08-12 audit Finding 14).
    def _cmd_skills_help(args: argparse.Namespace) -> int:
        skills_parser.print_help()
        return 1

    skills_parser.set_defaults(func=_cmd_skills_help)
    skills_install_parser = skills_subparsers.add_parser(
        "install",
        help=(
            "Install the packaged agent skills (mockymock, cobol-analysis, "
            "cobol-test, mockymock-setup) so a Claude Code or GitHub Copilot session can use them"
        ),
    )
    skills_install_parser.add_argument(
        "--project",
        action="store_true",
        help=(
            "Install into the current directory (./.claude/skills/<name>, "
            "or ./.github/skills/<name> for copilot) instead of the home "
            "directory"
        ),
    )
    skills_install_parser.add_argument(
        "--target",
        default="claude",
        # Literal rather than skills_cmd.TARGETS: see the deferred-import
        # rule; test_cli_skills.py pins the two together.
        choices=["claude", "copilot", "all"],
        help=(
            "Which assistant to install for: claude (~/.claude/skills, the "
            "default), copilot (GitHub Copilot: ~/.copilot/skills) or all"
        ),
    )
    skills_install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing install at the target path",
    )
    skills_install_parser.add_argument(
        "--skill",
        action="append",
        help=(
            "Install only this skill (repeatable): mockymock, cobol-analysis, "
            "cobol-test or mockymock-setup. Default: all four"
        ),
    )
    skills_install_parser.set_defaults(func=_cmd_skills_install)

    skills_plugin_parser = skills_subparsers.add_parser(
        "plugin",
        help=(
            "Write the cobol-testing Claude Code plugin as a local "
            "marketplace, for `/plugin marketplace add <dir>` without GitHub"
        ),
    )
    skills_plugin_parser.add_argument(
        "directory",
        nargs="?",
        help="Where to write it (default: ~/.mockymock/claude-plugin)",
    )
    skills_plugin_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an earlier export in that directory",
    )
    skills_plugin_parser.set_defaults(func=_cmd_skills_plugin)

    skills_mode_parser = skills_subparsers.add_parser(
        "mode",
        help=(
            "Show (or set) how much the AI assistant checks in while it builds a suite"
        ),
    )
    skills_mode_parser.add_argument(
        "--set",
        metavar="MODE",
        default=None,
        # Not `choices=MODES`: that would need mockymock.project.ai_mode
        # imported at parser-build time, and build_parser() runs on every
        # invocation including --help/--version. The valid set is spelled
        # out here instead and validated in _cmd_skills_mode;
        # tests/unit/test_cli_skills.py pins this text against MODES so the
        # two can't drift.
        help=(
            "Persist the mode to mockymock.toml: hands-on (propose first, "
            "wait for a yes), guided (narrate every step, stop at the "
            "checkpoints; the default), hands-off (run the whole workflow, "
            "report once at the end)"
        ),
    )
    skills_mode_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the active mode and every mode's contract as JSON",
    )
    skills_mode_parser.set_defaults(func=_cmd_skills_mode)
