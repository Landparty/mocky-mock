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
