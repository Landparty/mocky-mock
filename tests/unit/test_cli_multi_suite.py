"""Several suites per program, and suites under tests/: the PROGRAM line,
the four-step program lookup, default_suite_path, and `mockymock suites`.
See mockymock/cli/discovery.py and
docs/2026-10-14-multi-suite-layout-design.md."""

import json
from pathlib import Path

import pytest

from mockymock.cli.config import MockymockConfig
from mockymock.cli.discovery import (
    DiscoveryError,
    ProjectLayout,
    default_suite_path,
    find_suites,
    project_layout,
    read_program_line,
    resolve_cut_path,
    resolve_program,
    suite_base_name,
)
from mockymock.cli.main import main
from mockymock.dsl.parser import CutParseError, parse_cut


def _layout(root: Path, source: str = "src", tests: str = "tests") -> ProjectLayout:
    return ProjectLayout(
        root=root.resolve(),
        tests_dir=(root / tests).resolve(),
        source_root=(root / source).resolve(),
    )


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# -- the PROGRAM line -----------------------------------------------------


def test_parser_reads_program_line():
    suite = parse_cut(
        'TESTSUITE "S"\nPROGRAM "../src/PAY.cbl"\nTESTCASE "t"\n    PERFORM P\n'
    )
    assert suite.program_path == "../src/PAY.cbl"
    assert suite.program_line == 2


def test_parser_suite_without_program_line_has_none():
    suite = parse_cut('TESTSUITE "S"\nTESTCASE "t"\n    PERFORM P\n')
    assert suite.program_path is None


@pytest.mark.parametrize(
    "text, message",
    [
        ('PROGRAM "X.cbl"\nTESTSUITE "S"\n', "PROGRAM before TESTSUITE"),
        ('TESTSUITE "S"\nPROGRAM "A.cbl"\nPROGRAM "B.cbl"\n', "second PROGRAM line"),
        (
            'TESTSUITE "S"\nTESTCASE "t"\n    PERFORM P\nPROGRAM "A.cbl"\n',
            "right after the",
        ),
        ('TESTSUITE "S"\nPROGRAM ""\n', "path is empty"),
    ],
)
def test_parser_rejects_misplaced_program_lines(text, message):
    with pytest.raises(CutParseError, match=message):
        parse_cut(text)


def test_read_program_line_ignores_lines_after_first_testcase(tmp_path):
    cut = _write(tmp_path / "S.cut", 'TESTSUITE "S"\nTESTCASE "t"\nPROGRAM "X.cbl"\n')
    assert read_program_line(cut) is None


def test_suite_base_name_stops_at_first_dot():
    assert suite_base_name(Path("PAYROLL.cut")) == "PAYROLL"
    assert suite_base_name(Path("PAYROLL.errors.cut")) == "PAYROLL"


# -- the lookup, in order ----------------------------------------------------


def test_program_line_wins_over_every_convention(tmp_path):
    layout = _layout(tmp_path)
    _write(tmp_path / "src" / "PAY.cbl")
    other = _write(tmp_path / "legacy" / "OLD.cbl")
    cut = _write(
        tmp_path / "tests" / "PAY.cut", 'TESTSUITE "S"\nPROGRAM "../legacy/OLD.cbl"\n'
    )
    _write(tmp_path / "tests" / "PAY.cbl")  # a sibling that would otherwise win
    program, rule = resolve_program(cut, layout)
    assert (program.resolve(), rule) == (other.resolve(), "program")


def test_program_line_naming_a_missing_file_fails_instead_of_guessing(tmp_path):
    layout = _layout(tmp_path)
    _write(tmp_path / "src" / "PAY.cbl")
    cut = _write(tmp_path / "tests" / "PAY.cut", 'TESTSUITE "S"\nPROGRAM "TYPO.cbl"\n')
    with pytest.raises(DiscoveryError, match="TYPO.cbl"):
        resolve_program(cut, layout)


def test_sibling_still_pairs_and_beats_the_mirror(tmp_path):
    layout = _layout(tmp_path)
    sibling = _write(tmp_path / "tests" / "app" / "PAY.cbl")
    _write(tmp_path / "src" / "app" / "PAY.cbl")
    cut = _write(tmp_path / "tests" / "app" / "PAY.cut")
    assert resolve_program(cut, layout) == (sibling, "sibling")


def test_mirrored_suite_under_tests_finds_its_program(tmp_path):
    layout = _layout(tmp_path)
    program = _write(tmp_path / "src" / "app" / "PAY.cbl")
    cut = _write(tmp_path / "tests" / "app" / "PAY.cut")
    assert resolve_program(cut, layout) == (program.resolve(), "mirror")


def test_named_second_suite_pairs_by_base_name(tmp_path):
    layout = _layout(tmp_path)
    program = _write(tmp_path / "src" / "app" / "PAY.cbl")
    cut = _write(tmp_path / "tests" / "app" / "PAY.errors.cut")
    assert resolve_program(cut, layout) == (program.resolve(), "mirror")


def test_unique_name_under_source_root_is_found_from_anywhere(tmp_path):
    layout = _layout(tmp_path)
    program = _write(tmp_path / "src" / "deep" / "er" / "PAY.cbl")
    cut = _write(tmp_path / "tests" / "PAY.cut")
    assert resolve_program(cut, layout) == (program, "unique")


def test_two_programs_with_the_same_name_ask_for_a_program_line(tmp_path):
    layout = _layout(tmp_path)
    _write(tmp_path / "src" / "a" / "PAY.cbl")
    _write(tmp_path / "src" / "b" / "PAY.cbl")
    cut = _write(tmp_path / "tests" / "PAY.cut")
    with pytest.raises(DiscoveryError, match="PROGRAM"):
        resolve_program(cut, layout)


def test_no_program_anywhere_names_what_was_tried(tmp_path):
    layout = _layout(tmp_path)
    (tmp_path / "src").mkdir()
    cut = _write(tmp_path / "tests" / "x" / "PAY.cut")
    with pytest.raises(DiscoveryError) as exc_info:
        resolve_program(cut, layout)
    message = str(exc_info.value)
    assert "PAY.cob" in message and str(tmp_path / "src" / "x") in message


# -- program -> suites -------------------------------------------------------


def test_find_suites_collects_sibling_mirrored_named_and_declared(tmp_path):
    layout = _layout(tmp_path)
    program = _write(tmp_path / "src" / "app" / "PAY.cbl")
    expected = [
        _write(tmp_path / "src" / "app" / "PAY.cut"),
        _write(tmp_path / "tests" / "app" / "PAY.cut"),
        _write(tmp_path / "tests" / "app" / "PAY.errors.cut"),
        _write(
            tmp_path / "tests" / "regression" / "q3.cut",
            'TESTSUITE "q3"\nPROGRAM "../../src/app/PAY.cbl"\n',
        ),
    ]
    _write(tmp_path / "tests" / "app" / "OTHER.cut")
    assert find_suites(program, layout) == sorted(expected)


def test_resolve_cut_path_with_several_suites_asks_for_cut(tmp_path):
    layout = _layout(tmp_path)
    program = _write(tmp_path / "src" / "PAY.cbl")
    _write(tmp_path / "tests" / "PAY.cut")
    _write(tmp_path / "tests" / "PAY.errors.cut")
    with pytest.raises(DiscoveryError, match="2 suites"):
        resolve_cut_path(None, program, layout)


# -- where a new suite goes --------------------------------------------------


def test_default_suite_path_mirrors_the_program_folder_under_tests(tmp_path):
    layout = _layout(tmp_path)
    program = _write(tmp_path / "src" / "app" / "PAY.cbl")
    assert default_suite_path(program, layout) == layout.tests_dir / "app" / "PAY.cut"
    assert (
        default_suite_path(program, layout, "errors")
        == layout.tests_dir / "app" / "PAY.errors.cut"
    )


def test_default_suite_path_keeps_an_existing_sibling_layout(tmp_path):
    layout = _layout(tmp_path)
    program = _write(tmp_path / "src" / "PAY.cbl")
    sibling = _write(tmp_path / "src" / "PAY.cut")
    assert default_suite_path(program, layout) == sibling


def test_default_suite_path_beside_a_program_outside_the_source_root(tmp_path):
    layout = _layout(tmp_path / "project")
    program = _write(tmp_path / "elsewhere" / "PAY.cbl")
    assert default_suite_path(program, layout) == program.parent / "PAY.cut"


def test_every_default_suite_path_resolves_back_to_its_program(tmp_path):
    layout = _layout(tmp_path)
    program = _write(tmp_path / "src" / "a" / "b" / "PAY.cbl")
    for name in (None, "errors"):
        cut = _write(default_suite_path(program, layout, name))
        assert resolve_program(cut, layout)[0].resolve() == program.resolve()


def test_project_layout_defaults_and_config_overrides(tmp_path):
    default = project_layout(None, tmp_path)
    assert default.tests_dir == tmp_path.resolve() / "tests"
    assert default.source_root == tmp_path.resolve()

    (tmp_path / "src").mkdir()
    assert project_layout(None, tmp_path).source_root == tmp_path.resolve() / "src"

    config_file = _write(tmp_path / "mockymock.toml")
    config = MockymockConfig(
        source=config_file,
        sources=(config_file,),
        test_root=str(tmp_path / "unit"),
        source_root=str(tmp_path / "cobol"),
    )
    layout = project_layout(config)
    assert layout.tests_dir == (tmp_path / "unit").resolve()
    assert layout.source_root == (tmp_path / "cobol").resolve()


def test_source_root_config_key_resolves_against_the_config_file(tmp_path, monkeypatch):
    from mockymock.cli.config import load_config

    _write(tmp_path / "mockymock.toml", 'source_root = "src"\n')
    config = load_config(tmp_path)
    assert config.source_root == str(tmp_path / "src")


# -- the CLI -----------------------------------------------------------------


def test_suites_json_pairs_every_suite_and_names_the_rule(
    tmp_path, monkeypatch, capsys
):
    _write(tmp_path / "mockymock.toml", 'source_root = "src"\n')
    _write(tmp_path / "src" / "PAY.cbl")
    _write(tmp_path / "tests" / "PAY.cut")
    _write(tmp_path / "tests" / "LOST.cut")
    monkeypatch.chdir(tmp_path)
    assert main(["suites", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    by_name = {Path(row["cut"]).name: row for row in payload["suites"]}
    assert by_name["PAY.cut"]["rule"] == "mirror"
    assert by_name["LOST.cut"]["program"] is None
    assert "LOST" in by_name["LOST.cut"]["error"]
    assert payload["testsDir"] == str((tmp_path / "tests").resolve())


def test_suites_json_for_a_program_lists_its_suites_and_new_path(
    tmp_path, monkeypatch, capsys
):
    _write(tmp_path / "mockymock.toml", 'source_root = "src"\n')
    _write(tmp_path / "src" / "app" / "PAY.cbl")
    _write(tmp_path / "tests" / "app" / "PAY.cut")
    monkeypatch.chdir(tmp_path)
    assert main(["suites", "src/app/PAY.cbl", "--name", "errors", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [Path(p).name for p in payload["suites"]] == ["PAY.cut"]
    assert payload["newSuitePath"] == str(
        (tmp_path / "tests" / "app" / "PAY.errors.cut").resolve()
    )


def test_suites_for_a_missing_program_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["suites", "NOPE.cbl", "--json"]) == 1
    assert "no such file" in json.loads(capsys.readouterr().out)["error"]


def test_dotted_sibling_program_still_pairs_by_its_whole_stem(tmp_path):
    layout = _layout(tmp_path)
    program = _write(tmp_path / "src" / "A.B.cbl")
    cut = _write(tmp_path / "src" / "A.B.cut")
    assert resolve_program(cut, layout) == (program, "sibling")
