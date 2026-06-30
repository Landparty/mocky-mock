def test_cobolparser_is_importable_and_parses():
    from cobolparser import parse_cobol

    result = parse_cobol(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\n", filename="x.cbl"
    )
    assert result.ast is not None


def test_mockymock_has_a_version():
    import mockymock

    assert mockymock.__version__ == "0.1.0"
