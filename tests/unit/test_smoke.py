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


def test_uv_lock_records_the_pyproject_version():
    # release-please bumps pyproject.toml; uv.lock must follow (its
    # extra-files entry), or `uv sync --locked` fails every CI job after
    # the release (0.17.0 shipped with uv.lock still at 0.16.1).
    import tomllib
    from pathlib import Path

    root = Path(__file__).parents[2]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    (locked,) = [p["version"] for p in lock["package"] if p["name"] == "mockymock"]
    assert locked == pyproject["project"]["version"]
