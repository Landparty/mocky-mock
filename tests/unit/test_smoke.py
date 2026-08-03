def test_cobolparser_is_importable_and_parses():
    from cobolparser import parse_cobol

    result = parse_cobol("IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\n", filename="x.cbl")
    assert result.ast is not None


def test_mockymock_has_a_version():
    import tomllib
    from pathlib import Path

    import mockymock

    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text()
    )
    assert mockymock.__version__ == pyproject["project"]["version"]
