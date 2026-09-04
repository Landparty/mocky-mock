"""`CAPTURE ARG <n> INTO <target>` is scaffolded, and its storage is
synthesized.

Asserting on what a mocked `CALL` actually RECEIVED is usually the most
interesting assertion in a test, and the `CAPTURE ARG` grammar has supported
it since 2026-08-11 -- but only as hand-authoring, because the target had to
be an existing data item of a compatible type. Finding one (or adding it to
the program under test) before writing a single capture is what kept
`generate` from ever scaffolding one, and kept every capture a fully manual
step.

`splicer.captures` now declares a `UT-CAP-`-prefixed target on demand,
mirroring the captured argument's own PICTURE/USAGE, and resets it between
test cases. The reserved prefix is what keeps this from being a footgun: a
mistyped real data name never starts with `UT-CAP-`, so it can never
silently become a new field.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.generator import ProgramContext, scaffold_cut
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.captures import (
    CAPTURE_TARGET_PREFIX,
    capture_reset_lines,
    capture_target_name,
    capture_working_storage_lines,
    plan_captures,
)
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAPT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-PACKED          PIC S9(7)V99 COMP-3.
       01  WS-NAME            PIC X(20).
       01  WS-REC.
           05  WS-A           PIC X(4).
           05  WS-B           PIC X(6).
       01  WS-BINARY-REC.
           05  WS-C           PIC 9(4) COMP.
       01  WS-TABLE-GRP.
           05  WS-TABLE       PIC X(5) OCCURS 3 TIMES.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING WS-AMOUNT WS-PACKED WS-NAME WS-REC.
"""


def _context_and_surface(source: str = SOURCE):
    result = parse_cobol(source, filename="capt.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    return result.ast, surface, ProgramContext.build(result.ast, lines, surface)


def _scaffold(source: str = SOURCE) -> str:
    program, surface, context = _context_and_surface(source)
    return scaffold_cut(program.program_name, surface, None, frozenset(), context)


def test_generate_scaffolds_a_capture_for_every_mirrorable_argument():
    text = _scaffold()
    assert "CAPTURE ARG 1 INTO UT-CAP-DISCRATE-1" in text
    assert "CAPTURE ARG 2 INTO UT-CAP-DISCRATE-2" in text
    assert "CAPTURE ARG 3 INTO UT-CAP-DISCRATE-3" in text
    assert "CAPTURE ARG 4 INTO UT-CAP-DISCRATE-4" in text


def test_captures_come_first_in_the_mock_body():
    """`injector.build_site_dispatch` emits the capture MOVEs before the
    body's own statements, so a capture always reflects what the real caller
    passed rather than something a body line overwrote. The `.cut` reads the
    way it executes."""
    body = _scaffold().splitlines()
    first = next(i for i, line in enumerate(body) if "CAPTURE ARG 1" in line)
    move = next(i for i, line in enumerate(body) if "MOVE 0 TO RETURN-CODE" in line)
    assert first < move


def test_each_capture_gets_a_stub_expect_comment():
    """A captured value with nothing pointing at it is not an assertion.
    `run --record-expectations` promotes these to real `EXPECT` lines from
    an actual run -- the workflow that makes a captured argument useful
    without the author guessing the value up front."""
    text = _scaffold()
    assert "*> STUB EXPECT UT-CAP-DISCRATE-1" in text
    assert text.count("*> STUB EXPECT UT-CAP-DISCRATE-") == 4


def test_the_scaffolded_cut_lints_clean():
    """A scaffold that emits a refusable `.cut` is worse than one that emits
    less -- so the generator only scaffolds captures whose storage
    `plan_captures` will actually synthesize."""
    from mockymock.analysis.refusal import check_test_case

    program, surface, _ = _context_and_surface()
    suite = parse_cut(_scaffold())
    for case in suite.test_cases:
        assert check_test_case(surface, program, case) == [], case.name
    _, unresolved = plan_captures(program, suite, surface)
    assert unresolved == []


def test_synthesized_storage_mirrors_each_arguments_own_picture_and_usage():
    program, surface, _ = _context_and_surface()
    suite = parse_cut(_scaffold())
    plans, unresolved = plan_captures(program, suite, surface)
    assert unresolved == []
    declarations = capture_working_storage_lines(plans)
    assert "01  UT-CAP-DISCRATE-1  PIC 9(5)V99." in declarations
    assert "01  UT-CAP-DISCRATE-2  PIC S9(7)V99 USAGE COMP-3." in declarations
    assert "01  UT-CAP-DISCRATE-3  PIC X(20)." in declarations
    # A DISPLAY-only group is captured as one alphanumeric field of its own
    # byte length -- exactly what a group MOVE copies.
    assert "01  UT-CAP-DISCRATE-4  PIC X(10)." in declarations


def test_every_synthesized_target_is_reset_between_cases():
    """The suite compiles to ONE binary, so without a reset a case that
    never reached its CALL would assert against the previous case's captured
    value."""
    program, surface, _ = _context_and_surface()
    suite = parse_cut(_scaffold())
    plans, _ = plan_captures(program, suite, surface)
    resets = capture_reset_lines(plans)
    assert "MOVE ZERO TO UT-CAP-DISCRATE-1" in resets
    assert "MOVE SPACES TO UT-CAP-DISCRATE-3" in resets
    assert len(resets) == len(plans)


def test_unmirrorable_arguments_are_not_captured():
    """A table, and a group holding COMP data (an alphanumeric copy of it
    would compare unreadable bytes), are left out rather than scaffolded
    into something that would refuse or mislead."""
    source = SOURCE.replace(
        '           CALL "DISCRATE" USING WS-AMOUNT WS-PACKED WS-NAME WS-REC.',
        '           CALL "DISCRATE" USING WS-TABLE WS-BINARY-REC.',
    )
    text = _scaffold(source)
    assert "CAPTURE ARG" not in text


def test_a_target_the_program_already_declares_is_refused_not_redeclared():
    """Fail closed: silently synthesizing a second declaration of a name the
    program already uses would not compile."""
    source = SOURCE.replace(
        "       01  WS-AMOUNT          PIC 9(5)V99.",
        "       01  WS-AMOUNT          PIC 9(5)V99.\n"
        "       01  UT-CAP-DISCRATE-1  PIC X(4).",
    )
    program, surface, _ = _context_and_surface(source)
    suite = parse_cut(
        'TESTSUITE "s"\n'
        "\n"
        'TESTCASE "c"\n'
        '    MOCK CALL "DISCRATE"\n'
        "        CAPTURE ARG 1 INTO UT-CAP-DISCRATE-1\n"
        "        MOVE 0 TO RETURN-CODE\n"
        "    END-MOCK\n"
        "    PERFORM PROCESS-ORDER\n"
    )
    plans, unresolved = plan_captures(program, suite, surface)
    assert plans == []
    assert len(unresolved) == 1
    assert "already declared by the program itself" in unresolved[0]


def test_an_author_declared_target_is_left_alone():
    """Only the reserved prefix means "declare this for me" -- a capture
    into the program's own field keeps working exactly as before, with no
    synthesized declaration and no refusal."""
    program, surface, _ = _context_and_surface()
    suite = parse_cut(
        'TESTSUITE "s"\n'
        "\n"
        'TESTCASE "c"\n'
        '    MOCK CALL "DISCRATE"\n'
        "        CAPTURE ARG 1 INTO WS-NAME\n"
        "        MOVE 0 TO RETURN-CODE\n"
        "    END-MOCK\n"
        "    PERFORM PROCESS-ORDER\n"
    )
    plans, unresolved = plan_captures(program, suite, surface)
    assert plans == []
    assert unresolved == []


def test_capture_target_name_is_deterministic_and_a_valid_cobol_word():
    from mockymock.dsl.model import MockCategory

    name = capture_target_name(MockCategory.CALL, "A VERY LONG PROGRAM NAME INDEED", 2)
    assert name.startswith(CAPTURE_TARGET_PREFIX)
    assert len(name) <= 30
    assert not name.endswith("-")
    assert all(c.isalnum() or c == "-" for c in name)
