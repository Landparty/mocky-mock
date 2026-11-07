"""A test case that runs a program's whole main line (2026-11-02, NIST
CCVS85): `PERFORM <first> THRU <last>` with the STOP RUN it falls into
ending the case at `UT-PROGRAM-END`, and a mocked statement sharing its
line with a sentence that ends before it."""

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
    PROGRAM_END_PARAGRAPH,
    find_terminator_plans,
    program_end_thru,
    program_last_paragraph,
)
from mockymock.cli.main import _insert_driver, main
from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.driver import build_driver
from mockymock.splicer.injector import build_terminator_neutralization
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map


def _analyze(source: str):
    result = parse_cobol(source, filename="CCVS.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return result.ast, surface, scope_map, lines


def _suite(target: str, thru: str | None) -> MockTestSuite:
    case = MockTestCase(name="c", perform_target=target, perform_thru=thru)
    return MockTestSuite(name="S", test_cases=[case])


# The CCVS85 shape: the first paragraph GO TOs past the closing code, the
# tests run, and the last paragraph GO TOs back to it; STOP RUN is only
# ever fallen into.
CCVS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CCVS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO "PRT".
       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE.
       01  PRINT-REC PIC X(20).
       WORKING-STORAGE SECTION.
       01  PASS-COUNTER PIC 999 VALUE 0.
       PROCEDURE DIVISION.
       CCVS1 SECTION.
       OPEN-FILES.
           OPEN OUTPUT PRINT-FILE.
           GO TO CCVS1-EXIT.
       CLOSE-FILES.
           PERFORM END-ROUTINE. CLOSE PRINT-FILE.
       TERMINATE-CCVS.
           STOP RUN.
       END-ROUTINE.
           MOVE "END" TO PRINT-REC.
           WRITE PRINT-REC.
       CCVS1-EXIT.
           EXIT.
       TEST-SECTION SECTION.
       TEST-1.
           ADD 1 TO PASS-COUNTER.
       TEST-2.
           ADD 1 TO PASS-COUNTER.
       CCVS-EXIT SECTION.
       CCVS-999999.
           GO TO CLOSE-FILES.
"""


# --- a statement after a sentence that ends on its line --------------------


def _site(surface, label: str):
    return next(site for site in surface.boundary_sites if site.label == label)


def test_a_statement_after_a_closed_sentence_keeps_that_sentence_as_its_lead():
    _, surface, _, _ = _analyze(CCVS)
    close = _site(surface, "CLOSE")
    assert close.unspliceable_reason is None
    assert close.span_lead is not None
    assert close.span_lead.strip() == "PERFORM END-ROUTINE."


def test_a_statement_inside_an_open_sentence_still_does_not_own_its_line():
    source = CCVS.replace(
        "PERFORM END-ROUTINE. CLOSE PRINT-FILE.",
        "PERFORM END-ROUTINE CLOSE PRINT-FILE.",
    )
    _, surface, _, _ = _analyze(source)
    close = _site(surface, "CLOSE")
    assert close.unspliceable_reason == "does not start its own line"
    assert close.span_lead is None


def test_a_one_line_paragraph_still_does_not_own_its_line():
    """`CLOSE-FILES. CLOSE PRINT-FILE.`: a MOCK PARAGRAPH splices that header
    line, so its statement is not split off."""
    source = CCVS.replace(
        "       CLOSE-FILES.\n           PERFORM END-ROUTINE. CLOSE PRINT-FILE.",
        "       CLOSE-FILES. CLOSE PRINT-FILE.",
    )
    _, surface, _, _ = _analyze(source)
    assert _site(surface, "CLOSE").unspliceable_reason == "does not start its own line"


def test_a_statement_followed_on_its_line_still_shares_it():
    source = CCVS.replace(
        "PERFORM END-ROUTINE. CLOSE PRINT-FILE.",
        "PERFORM END-ROUTINE. CLOSE PRINT-FILE. MOVE 1 TO PASS-COUNTER.",
    )
    _, surface, _, _ = _analyze(source)
    assert "shares its line" in (_site(surface, "CLOSE").unspliceable_reason or "")


def test_a_literal_ending_in_a_period_is_no_closed_sentence():
    source = CCVS.replace(
        "PERFORM END-ROUTINE. CLOSE PRINT-FILE.",
        'MOVE "A." TO PRINT-REC CLOSE PRINT-FILE.',
    )
    _, surface, _, _ = _analyze(source)
    assert _site(surface, "CLOSE").unspliceable_reason == "does not start its own line"


# --- the terminator that ends the main line ---------------------------------


def test_the_last_paragraph_is_the_programs_last_in_source_order():
    program, *_ = _analyze(CCVS)
    assert program_last_paragraph(program) == "CCVS-999999"


def test_a_fallen_into_stop_run_ends_a_main_line_case():
    program, surface, scope_map, lines = _analyze(CCVS)
    plans, reasons = find_terminator_plans(
        surface, program, _suite("OPEN-FILES", "CCVS-999999"), scope_map, lines
    )
    assert reasons == []
    assert [(p.site.label, p.exit_kind, p.chain_performs) for p in plans] == [
        ("STOP RUN", "PROGRAM", [])
    ]
    assert program_end_thru(program, plans) == "CCVS-999999"


def test_the_same_stop_run_is_still_refused_for_a_bare_perform():
    program, surface, scope_map, lines = _analyze(CCVS)
    plans, reasons = find_terminator_plans(
        surface, program, _suite("OPEN-FILES", None), scope_map, lines
    )
    assert [p.exit_kind for p in plans] == ["RETURN"]
    assert reasons == []
    assert program_end_thru(program, plans) is None


def test_a_stop_run_the_program_also_performs_cannot_end_the_main_line():
    source = CCVS.replace(
        "       TEST-2.\n           ADD 1 TO PASS-COUNTER.\n",
        "       TEST-2.\n           PERFORM TERMINATE-CCVS.\n",
    )
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(
        surface, program, _suite("OPEN-FILES", "CCVS-999999"), scope_map, lines
    )
    assert [p.exit_kind for p in plans] == ["RETURN"]
    assert reasons == []


TWO_PARAGRAPHS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOPARA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       P1.
           MOVE 1 TO WS-X.
       P2.
           STOP RUN.
"""


def test_a_stop_run_ending_another_cases_perform_is_refused_for_the_main_line():
    """One statement, two neutralizations: EXIT PARAGRAPH for a case that
    PERFORMs its paragraph, GO TO UT-PROGRAM-END for the main line."""
    program, surface, scope_map, lines = _analyze(TWO_PARAGRAPHS)
    alone = MockTestCase(name="a", perform_target="P2")
    main_line = MockTestCase(name="b", perform_target="P1", perform_thru="P2")
    for cases in ([alone], [main_line]):
        plans, reasons = find_terminator_plans(
            surface,
            program,
            MockTestSuite(name="S", test_cases=cases),
            scope_map,
            lines,
        )
        assert reasons == [] and len(plans) == 1
    for cases in ([alone, main_line], [main_line, alone]):
        plans, reasons = find_terminator_plans(
            surface,
            program,
            MockTestSuite(name="S", test_cases=cases),
            scope_map,
            lines,
        )
        # Neither way serves both cases; a GOBACK to the test does.
        assert [p.exit_kind for p in plans] == ["RETURN"]
        assert reasons == []


def test_the_main_line_end_is_a_go_to_the_program_end_paragraph():
    assert build_terminator_neutralization("PROGRAM", "4") == [
        "           MOVE 4 TO RETURN-CODE",
        '           MOVE "Y" TO UT-EARLY-EXIT',
        f"           GO TO {PROGRAM_END_PARAGRAPH}",
    ]


def test_the_driver_runs_thru_the_program_end_paragraph():
    suite = parse_cut(
        'TESTSUITE "S"\n\nTESTCASE "main"\n'
        "    PERFORM OPEN-FILES THRU CCVS-999999\n\n"
        'TESTCASE "one"\n    PERFORM TEST-1 THRU TEST-2\n'
    )
    artifact = build_driver(suite, [], TallyRegistry(suite), program_end="CCVS-999999")
    assert artifact.program_end
    performs = [line.strip() for line in artifact.procedure_lines if "THRU" in line]
    assert performs == [
        f"PERFORM OPEN-FILES THRU {PROGRAM_END_PARAGRAPH}",
        "PERFORM TEST-1 THRU TEST-2",
    ]
    lines = normalize_fixed_format(CCVS.splitlines()).splitlines()
    instrumented = [line.strip() for line in _insert_driver(lines, artifact)]
    end = instrumented.index(f"{PROGRAM_END_PARAGRAPH}.")
    assert instrumented[end + 1] == "EXIT."
    # After the program's last paragraph, before the end-of-program trap.
    assert end > instrumented.index("GO TO CLOSE-FILES.")
    assert instrumented[end + 2 :].index("UT-END-OF-PROGRAM SECTION.") >= 0


def test_without_a_main_line_end_the_driver_is_unchanged():
    suite = parse_cut('TESTSUITE "S"\n\nTESTCASE "one"\n    PERFORM A THRU B\n')
    artifact = build_driver(suite, [], TallyRegistry(suite))
    assert not artifact.program_end
    assert any(line.strip() == "PERFORM A THRU B" for line in artifact.procedure_lines)
    lines = normalize_fixed_format(CCVS.splitlines()).splitlines()
    assert f"{PROGRAM_END_PARAGRAPH}." not in [
        line.strip() for line in _insert_driver(lines, artifact)
    ]


# --- generate ----------------------------------------------------------------


def _generate(tmp_path: Path, source: str) -> str:
    program = tmp_path / "CCVS.cbl"
    program.write_text(source)
    cut = tmp_path / "CCVS.cut"
    assert (
        main(
            ["generate", str(program), "-o", str(cut), "--force", "--scenarios", "all"]
        )
        == 0
    )
    return cut.read_text()


def test_generate_runs_the_main_line_when_the_first_paragraph_goes_on(tmp_path):
    cases = parse_cut(_generate(tmp_path, CCVS)).test_cases
    assert cases
    assert {(c.perform_target, c.perform_thru) for c in cases} == {
        ("OPEN-FILES", "CCVS-999999")
    }


def test_generate_keeps_a_bare_perform_when_the_first_paragraph_stops(tmp_path):
    source = CCVS.replace("           GO TO CCVS1-EXIT.\n", "           STOP RUN.\n")
    cases = parse_cut(_generate(tmp_path, source)).test_cases
    assert {(c.perform_target, c.perform_thru) for c in cases} == {("OPEN-FILES", None)}


def test_the_spliced_line_keeps_its_closed_sentence(tmp_path):
    program = tmp_path / "CCVS.cbl"
    program.write_text(CCVS)
    cut = tmp_path / "CCVS.cut"
    cut.write_text(
        'TESTSUITE "S"\n\nTESTCASE "main"\n    MOCK OPEN PRINT-FILE\n    END-MOCK\n'
        "    MOCK CLOSE PRINT-FILE\n    END-MOCK\n    MOCK WRITE PRINT-REC\n"
        "    END-MOCK\n    PERFORM OPEN-FILES THRU CCVS-999999\n"
        "    EXPECT PASS-COUNTER TO BE 2\n"
    )
    out = tmp_path / "out.cbl"
    assert main(["export", str(program), "--cut", str(cut), "-o", str(out)]) == 0
    code = [line[6:72].rstrip() for line in out.read_text().splitlines()]
    shared = next(
        i for i, line in enumerate(code) if "PERFORM END-ROUTINE. CLOSE" in line
    )
    assert code[shared].lstrip().startswith("*>")
    assert code[shared + 1].strip() == "PERFORM END-ROUTINE."
    assert "UT-CURRENT-CASE" in " ".join(code[shared + 2 : shared + 12])
    stop = next(i for i, line in enumerate(code) if "*>" in line and "STOP" in line)
    assert code[stop].lstrip().startswith("*>")
    assert f"GO TO {PROGRAM_END_PARAGRAPH}" in " ".join(code[stop : stop + 4])
    assert any(
        line.strip() == f"PERFORM OPEN-FILES THRU {PROGRAM_END_PARAGRAPH}"
        for line in code
    )


def test_generate_writes_each_check_once(tmp_path):
    """A record written by several WRITE sites gave one identical `*> STUB
    EXPECT` line per site (80 for NIST SQ101M's PRINT-REC)."""
    source = CCVS.replace(
        "       TEST-2.\n           ADD 1 TO PASS-COUNTER.\n",
        "       TEST-2.\n           ADD 1 TO PASS-COUNTER.\n"
        "           WRITE PRINT-REC.\n           WRITE PRINT-REC.\n",
    )
    text = _generate(tmp_path, source)
    for block in text.split("\nTESTCASE ")[1:]:
        checks = [line for line in block.splitlines() if "EXPECT PRINT-REC" in line]
        assert len(checks) == len(set(checks)) == 1


def test_a_long_reset_move_is_wrapped():
    """NIST NC207A: an item 49 levels deep is reset by a MOVE whose `IN`
    chain passed cobc's 512-byte line limit, and the truncated name was
    ambiguous."""
    from mockymock.splicer.driver import wrap_words

    chain = " ".join(f"IN GROUP-{n:02d}" for n in range(48, 0, -1))
    line = f"           MOVE SPACES TO GROUP-49-1 {chain}."
    wrapped = wrap_words(line)
    assert len(wrapped) > 1
    assert all(len(part) <= 104 for part in wrapped)
    assert " ".join(part.strip() for part in wrapped) == line.strip()
    assert wrap_words('           MOVE "A  B" TO X') == ['           MOVE "A  B" TO X']


GO_TO_ON_END = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOEND.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TFIL ASSIGN TO "IN".
           SELECT TFIL2 ASSIGN TO "OUT".
       DATA DIVISION.
       FILE SECTION.
       FD  TFIL.
       01  TREC PIC X(4).
       FD  TFIL2.
       01  TREC2 PIC X(4).
       PROCEDURE DIVISION.
       P-CONTROL.
           OPEN INPUT TFIL.
           READ TFIL
               AT END
                   GO TO P-END.
           OPEN OUTPUT TFIL2.
           WRITE TREC2 FROM TREC.
       P-END.
           CLOSE TFIL.
           STOP RUN.
"""


def test_a_count_after_a_go_to_branch_is_not_exact(tmp_path):
    """NIST RW301M: `READ TFIL AT END GO TO RW301M-END` skips the OPEN
    after it on empty input, which was VERIFYed as called once."""
    program = tmp_path / "GOEND.cbl"
    program.write_text(GO_TO_ON_END)
    cut = tmp_path / "GOEND.cut"
    main(["generate", str(program), "-o", str(cut), "--force", "--scenarios", "all"])
    cases = {case.name: case for case in parse_cut(cut.read_text()).test_cases}
    assert "empty input" in cases
    assert not [v for v in cases["empty input"].verifications if "TFIL2" in str(v.key)]


def test_a_perform_of_a_go_to_target_returns_at_its_end():
    """NIST NC105A: `PERFORM MOVE-WRITE-F1-32`, a paragraph the main line
    also GO TOs, returns at that paragraph's end -- it does not fall on
    into TERMINATE-CCVS, so that STOP RUN still ends the main line."""
    source = CCVS.replace(
        "       TEST-1.\n           ADD 1 TO PASS-COUNTER.\n",
        "       TEST-1.\n           ADD 1 TO PASS-COUNTER.\n"
        "           PERFORM TEST-2.\n           GO TO TEST-2.\n",
    )
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(
        surface, program, _suite("OPEN-FILES", "CCVS-999999"), scope_map, lines
    )
    assert reasons == []
    assert [p.exit_kind for p in plans] == ["PROGRAM"]


def test_a_go_to_out_of_a_performed_range_still_counts_as_inside_it():
    source = CCVS.replace(
        '       END-ROUTINE.\n           MOVE "END" TO PRINT-REC.\n',
        '       END-ROUTINE.\n           MOVE "END" TO PRINT-REC.\n'
        "           IF PASS-COUNTER = 9 GO TO TERMINATE-CCVS.\n",
    )
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(
        surface, program, _suite("OPEN-FILES", "CCVS-999999"), scope_map, lines
    )
    assert [p.exit_kind for p in plans] == ["RETURN"]
    assert reasons == []


# TEST-2's WRITE, nested in an IF, has INVALID KEY and no END-WRITE, so no
# MOCK can replace it: the whole main line reaches it, OPEN-FILES alone (here
# falling through instead of GO TO) does not.
UNMOCKABLE_TAIL = (
    CCVS.replace(
        "           GO TO CCVS1-EXIT.\n", "           MOVE 0 TO PASS-COUNTER.\n"
    )
    .replace(
        "       TEST-2.\n           ADD 1 TO PASS-COUNTER.\n",
        "       TEST-2.\n           ADD 1 TO PASS-COUNTER.\n"
        "           IF PASS-COUNTER LESS THAN 9\n"
        "               WRITE IX-REC\n"
        "                   INVALID KEY ADD 1 TO PASS-COUNTER.\n"
        "           ADD 1 TO PASS-COUNTER.\n",
    )
    .replace(
        '           SELECT PRINT-FILE ASSIGN TO "PRT".\n',
        '           SELECT PRINT-FILE ASSIGN TO "PRT".\n'
        '           SELECT IX-FILE ASSIGN TO "IX" ORGANIZATION INDEXED\n'
        "               ACCESS RANDOM RECORD KEY IX-KEY.\n",
    )
    .replace(
        "       WORKING-STORAGE SECTION.\n",
        "       FD  IX-FILE.\n       01  IX-REC.\n           05 IX-KEY PIC X(4).\n"
        "       WORKING-STORAGE SECTION.\n",
    )
)


def test_generate_keeps_the_bare_perform_when_the_main_line_is_refused(
    tmp_path, capsys
):
    cases = parse_cut(_generate(tmp_path, UNMOCKABLE_TAIL)).test_cases
    assert {c.perform_thru for c in cases} == {None}
    assert "PERFORM their entry paragraph alone" in capsys.readouterr().err


def test_comment_entries_become_comments():
    """NIST SG101A / RW101A: AUTHOR and INSTALLATION text on the lines below
    the paragraph name compiled as code in free form."""
    from mockymock.cli.main import comment_out_comment_entries

    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID.",
        "    SG101A.",
        "AUTHOR.",
        "    FEDERAL COMPILER TESTING CENTER.",
        "INSTALLATION. GSA",
        "    SOFTWARE DEVELOPMENT OFFICE.",
        "",
        "    FALLS CHURCH VIRGINIA 22041.",
        "ENVIRONMENT DIVISION.",
        "    AUTHOR.",
    ]
    out = comment_out_comment_entries(lines)
    assert out[:4] == lines[:4]
    assert out[4] == "      *> FEDERAL COMPILER TESTING CENTER."
    assert out[5] == lines[5]
    assert out[6].startswith("      *> SOFTWARE")
    assert out[8].startswith("      *> FALLS")
    assert out[9:] == lines[9:]


# Regression: LegacyLens "Create tests" (generate, record, play) over the NIST
# CCVS85 suite, 2026-11-02 (examples/nist-cobol85/generated/README.md).


def _nist_generate(tmp_path: Path, name: str, source: str, capsys) -> tuple[str, str]:
    program = tmp_path / f"{name}.cbl"
    program.write_text(source)
    cut = tmp_path / f"{name}.cut"
    main(["generate", str(program), "-o", str(cut), "--force", "--scenarios", "all"])
    return cut.read_text(), capsys.readouterr().err


# --- generate: identical cases (72 NIST suites) ----------------------------

FALLS_THROUGH = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN"
               FILE STATUS IS WS-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-CODE  PIC X.
       WORKING-STORAGE SECTION.
       01  WS-STATUS PIC XX.
       01  WS-OUT    PIC X(4).
       PROCEDURE DIVISION.
       START-UP.
           MOVE SPACES TO WS-OUT.
           OPEN INPUT IN-FILE.
       MAIN-LINE.
           READ IN-FILE.
           IF IN-CODE = "A"
               MOVE "AAAA" TO WS-OUT
           ELSE
               MOVE "BBBB" TO WS-OUT
           END-IF.
           CLOSE IN-FILE.
           STOP RUN.
"""


def test_a_first_paragraph_that_runs_on_gets_main_line_cases(tmp_path, capsys):
    """START-UP falls through into MAIN-LINE, where the IF the branch
    scenarios target sits: every case runs the main line THRU the last
    paragraph, so each branch case takes its own branch."""
    text, _ = _nist_generate(tmp_path, "FALLS", FALLS_THROUGH, capsys)
    cases = parse_cut(text).test_cases
    assert {(c.perform_target, c.perform_thru) for c in cases} == {
        ("START-UP", "MAIN-LINE")
    }
    names = [case.name for case in cases]
    assert any("IF@" in name and "THEN" in name for name in names)
    assert any("IF@" in name and "ELSE" in name for name in names)
    assert "left out" not in text


# MAIN-LINE is PERFORMed too, so its STOP RUN cannot end a main-line range,
# and sharing its line with the CLOSE it cannot be spliced into a GOBACK to
# the test either: the cases keep their bare PERFORM START-UP.
PERFORMED_TOO = (
    FALLS_THROUGH.replace(
        "           CLOSE IN-FILE.\n           STOP RUN.\n",
        "           CLOSE IN-FILE. STOP RUN.\n",
    )
    + """       RETRY-PARA.
           PERFORM MAIN-LINE.
"""
)


def test_a_performed_main_line_runs_through_when_its_stop_run_can_goback(
    tmp_path, capsys
):
    """With the STOP RUN on a line of its own, the planner GOBACKs from it to
    the test (the call frame), so the main line runs THRU the last paragraph
    and every branch case takes its own branch."""
    source = (
        FALLS_THROUGH
        + """       RETRY-PARA.
           PERFORM MAIN-LINE.
"""
    )
    text, _ = _nist_generate(tmp_path, "FALLS", source, capsys)
    cases = parse_cut(text).test_cases
    assert {(c.perform_target, c.perform_thru) for c in cases} == {
        ("START-UP", "RETRY-PARA")
    }
    names = [case.name for case in cases]
    assert any("IF@" in name and "THEN" in name for name in names)
    assert any("IF@" in name and "ELSE" in name for name in names)


def test_scenarios_whose_case_repeats_an_earlier_one_are_left_out(tmp_path, capsys):
    """A case PERFORMs START-UP alone, so every branch case came out
    identical to the happy path under a name claiming a branch it never
    takes (NIST: IX215A ran one case 83 times)."""
    text, err = _nist_generate(tmp_path, "FALLS", PERFORMED_TOO, capsys)
    assert {c.perform_thru for c in parse_cut(text).test_cases} == {None}
    names = [case.name for case in parse_cut(text).test_cases]
    assert "happy path" in names
    assert not any("IF@" in name for name in names)
    assert "scenario(s) left out" in text
    assert "PERFORMs START-UP alone" in err
    bodies = [
        tuple(
            line.strip()
            for line in block.splitlines()[1:]
            if line.strip() and not line.strip().startswith("*>")
        )
        for block in text.split("\nTESTCASE ")[1:]
    ]
    assert len(bodies) == len(set(bodies))


def test_distinct_branch_cases_are_all_kept(tmp_path, capsys):
    """The same program with its main line in one paragraph: every branch
    case differs from the happy path, and none is dropped."""
    source = FALLS_THROUGH.replace(
        "           OPEN INPUT IN-FILE.\n       MAIN-LINE.\n",
        "           OPEN INPUT IN-FILE.\n",
    )
    text, _ = _nist_generate(tmp_path, "FALLS", source, capsys)
    names = [case.name for case in parse_cut(text).test_cases]
    assert any("IF@" in name and "THEN" in name for name in names)
    assert any("IF@" in name and "ELSE" in name for name in names)
    assert "left out" not in text
