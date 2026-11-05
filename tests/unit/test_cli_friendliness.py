"""First-run friendliness of the mockymock CLI: help, typos, stray
arguments and toolchain errors."""

import argparse

import pytest

from mockymock.cli.main import _GROUPED_COMMANDS, build_parser, main


def _registered() -> list[str]:
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return list(action.choices)
    raise AssertionError("no subcommands")


def test_every_command_is_in_exactly_one_help_group():
    assert len(_GROUPED_COMMANDS) == len(set(_GROUPED_COMMANDS))
    assert set(_GROUPED_COMMANDS) == set(_registered())


def test_top_level_help_lists_commands_once():
    text = build_parser().format_help()
    assert "usage: mockymock <command> [options]" in text
    assert "{setup,init" not in text
    assert "Quick start:" in text
    assert "MOCKYMOCK_GNUCOBOL_HOME" in text


def test_bare_invocation_prints_help_and_exits_2(capsys):
    assert main([]) == 2
    assert "Everyday:" in capsys.readouterr().out


def test_subcommand_usage_names_the_subcommand(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--help"])
    assert capsys.readouterr().out.startswith("usage: mockymock run ")


def test_mistyped_command_gets_a_suggestion(capsys):
    assert main(["rnu", "PROG.cbl"]) == 2
    err = capsys.readouterr().err
    assert "unknown command 'rnu' (did you mean 'run'?)" in err


def test_unrelated_word_gets_no_suggestion(capsys):
    assert main(["zzzzzz"]) == 2
    err = capsys.readouterr().err
    assert "unknown command 'zzzzzz'" in err
    assert "did you mean" not in err


def test_stray_cut_argument_points_at_the_cut_flag(capsys):
    assert main(["run", "PROG.cbl", "PROG.cut"]) == 2
    err = capsys.readouterr().err
    assert "usage: mockymock run" in err
    assert "use --cut PROG.cut" in err


def test_bad_toolchain_choice_is_a_clean_error(tmp_path, monkeypatch, capsys):
    (tmp_path / "PROG.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PROG.\n"
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n",
        encoding="utf-8",
    )
    (tmp_path / "PROG.cut").write_text(
        'TESTSUITE "prog"\n\nTESTCASE "t"\n    PERFORM MAIN-PARA\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOCKYMOCK_TOOLCHAIN", "bogus")
    assert main(["run", "PROG.cbl"]) == 1
    out = capsys.readouterr().out
    assert "MOCKYMOCK_TOOLCHAIN='bogus' is not one of auto, docker, native" in out
    assert "Traceback" not in out


def test_path_options_show_file_and_dir_metavars():
    text = build_parser()._subparsers._group_actions[0].choices["run"].format_help()
    assert "--junit-xml FILE" in text
    assert "--copybook-path DIR" in text
    assert "--json-report JSON_REPORT" not in text
    assert "exit codes:" in text
