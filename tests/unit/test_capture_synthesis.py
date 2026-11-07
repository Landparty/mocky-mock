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


def test_every_pipeline_that_builds_reset_lines_resets_the_captures():
    """The suite compiles to ONE binary in `run`, `debug`, `export` AND
    `mutate` alike, so a capture target left unreset in any one of them
    lets a case that never reached its CALL assert against the previous
    case's value. In `mutate` that is worse than a wrong assertion: the
    stale value can "kill" a mutant the suite never actually noticed,
    inflating the score.

    This is a source-shape guard rather than a behavioural one because the
    four pipelines each assemble their own `reset_lines` before a compile
    that needs Docker -- and the way this broke once already was exactly
    that: a merge restored one of the four call sites from a revision that
    predated the capture resets, and nothing failed."""
    import ast as _ast
    from pathlib import Path

    def _calls(tree, name):
        return sum(
            1
            for node in _ast.walk(tree)
            if isinstance(node, _ast.Call)
            and isinstance(node.func, _ast.Name)
            and node.func.id == name
        )

    root = Path(__file__).resolve().parents[2] / "mockymock"
    commands = root / "cli" / "commands"
    for path in (
        commands / "run.py",
        commands / "debug.py",
        commands / "export.py",
        root / "mutation" / "runner.py",
    ):
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        builds = _calls(tree, "reset_move_lines")
        resets = _calls(tree, "extra_reset_lines_for")
        assert builds > 0, f"{path} no longer assembles reset_lines at all"
        assert builds == resets, (
            f"{path} assembles reset_lines {builds} time(s) but appends the "
            f"synthesized CAPTURE target resets {resets} time(s)"
        )


def test_a_nameless_argument_is_unresolved_not_a_crash():
    """`CallParameter.name` is a `str` by contract and cobol-parser's CALL
    parser substitutes "OMITTED" rather than emitting an empty one -- so
    this shape cannot arise today. It is guarded anyway because this
    comprehension is the only place a violation of that contract would
    surface, and it would surface as an AttributeError out of the
    static-check pass: a crash where the whole point of `plan_captures` is
    to hand back a readable UNRESOLVED_CAPTURE_TARGET reason."""
    program, surface, _ = _context_and_surface()
    suite = parse_cut(_scaffold())
    for site in surface.boundary_sites:
        for param in getattr(site.statement, "using_parameters", []) or []:
            param.name = None  # type: ignore[assignment]

    plans, unresolved = plan_captures(program, suite, surface)
    assert plans == []
    assert unresolved
    assert all("no resolvable data item" in reason for reason in unresolved)


_TWO_SITES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOCALL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME            PIC X(5).
       01  WS-QTY             PIC 9(3).
       01  WS-OTHER           PIC 9(3).
       01  WS-WIDE            PIC 9(5).

       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUB" USING WS-NAME WS-QTY
           PERFORM SECOND-PARA
           GOBACK.
       SECOND-PARA.
           CALL "SUB" USING WS-NAME {second}.
"""


def test_a_key_with_several_agreeing_call_sites_is_still_captured():
    """Two CALLs of one program passing the same items agree, so both
    arguments are scaffolded. The agreement check used to compare the
    distinct-name set's size with the number of sites, so every key with
    two or more CALL sites got no captures at all -- the common shape, since
    a subprogram is rarely called from exactly one place."""
    text = _scaffold(_TWO_SITES.format(second="WS-QTY"))
    assert "CAPTURE ARG 1 INTO UT-CAP-SUB-1" in text
    assert "CAPTURE ARG 2 INTO UT-CAP-SUB-2" in text
    program, surface, _ = _context_and_surface(_TWO_SITES.format(second="WS-QTY"))
    _, unresolved = plan_captures(program, parse_cut(text), surface)
    assert unresolved == []


def test_only_the_argument_the_sites_disagree_on_is_left_uncaptured():
    text = _scaffold(_TWO_SITES.format(second="WS-WIDE"))
    assert "CAPTURE ARG 1 INTO UT-CAP-SUB-1" in text
    assert "CAPTURE ARG 2" not in text


def test_different_items_of_one_layout_are_captured_into_one_field():
    """WS-QTY and WS-OTHER are both PIC 9(3): one synthesized field mirrors
    either, so the sites agree (an IMS program's DLI-GU and DLI-ISRT
    function codes through one CBLTDLI mock are the motivating case)."""
    text = _scaffold(_TWO_SITES.format(second="WS-OTHER"))
    assert "CAPTURE ARG 2 INTO UT-CAP-SUB-2" in text


def test_an_argument_a_site_does_not_pass_is_left_uncaptured():
    """A site with fewer arguments would trip CAPTURE_ARG_OUT_OF_RANGE."""
    text = _scaffold(_TWO_SITES.format(second="").replace(" .", "."))
    assert "CAPTURE ARG 1 INTO UT-CAP-SUB-1" in text
    assert "CAPTURE ARG 2" not in text


LITERAL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAPL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ABC                PIC 9(2).
       01  WS-AMT             PIC 9(3).

       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUBX" USING BY CONTENT "ABC" 'HELLO'
               BY REFERENCE WS-AMT.
"""

LITERAL_CUT = """\
TESTSUITE "S"
TESTCASE "literal captures"
    MOCK CALL "SUBX"
        CAPTURE ARG 1 INTO UT-CAP-SUBX-1
        CAPTURE ARG 2 INTO UT-CAP-SUBX-2
        CAPTURE ARG 3 INTO UT-CAP-SUBX-3
    END-MOCK
    PERFORM MAIN-PARA
"""


def test_a_literal_argument_is_mirrored_as_the_literal_not_a_same_named_item():
    """cobolparser reports `"ABC"` as the bare name ABC. The injector MOVEs
    the literal (fixed 2026-09-28 round 4), but the synthesized UT-CAP-
    target used to mirror the unrelated item ABC (PIC 9(2) -- a MOVE of
    "ABC" into it is not "ABC"), and to refuse a literal with no same-named
    item ('HELLO') as "not a uniquely-named data item"."""
    result = parse_cobol(LITERAL_SOURCE, filename="capl.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(LITERAL_SOURCE.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    plans, unresolved = plan_captures(
        result.ast, parse_cut(LITERAL_CUT), surface, lines
    )
    assert unresolved == []
    declarations = capture_working_storage_lines(plans)
    assert "01  UT-CAP-SUBX-1  PIC X(3)." in declarations
    assert "01  UT-CAP-SUBX-2  PIC X(5)." in declarations
    assert "01  UT-CAP-SUBX-3  PIC 9(3)." in declarations


def test_literal_declarations_mirror_the_literal_itself():
    """Numeric literals are covered here rather than end to end: PyPI
    cobol-parser 1.8.4 drops a numeric USING operand (and everything after
    it) from `using_parameters`, which the gate already refuses as
    CAPTURE_ARG_OUT_OF_RANGE."""
    from mockymock.splicer.captures import _literal_declaration

    assert _literal_declaration("T", '"ABC"') == (
        "01  T  PIC X(3).",
        "MOVE SPACES TO T",
    )
    assert _literal_declaration("T", "'D''E'")[0] == "01  T  PIC X(3)."
    assert _literal_declaration("T", "42") == ("01  T  PIC 9(2).", "MOVE ZERO TO T")
    assert _literal_declaration("T", "-3.25")[0] == "01  T  PIC S9(1)V9(2)."
    assert _literal_declaration("T", 'X"C1C2"') is None
    assert _literal_declaration("T", '""') is None


_LITERAL_VS_ITEM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAPM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ABC                PIC X(3).
       01  WS-A               PIC X(5).

       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUBP" USING {first} WS-A.
           CALL "SUBP" USING {second} WS-A.
"""


def test_generate_never_scaffolds_a_capture_of_a_literal_argument():
    """`USING "ABC"` with an item named ABC in the program: the bare names
    matched ABC, so a capture of a value the source fixes was scaffolded.
    (No numeric literal here: cobol-parser 1.8.x drops one from
    `using_parameters`, and the text re-scan then trusts nothing.)"""
    text = _scaffold(_LITERAL_VS_ITEM.format(first='"ABC"', second='"ABC"'))
    assert "CAPTURE ARG 1" not in text
    assert "CAPTURE ARG 2 INTO UT-CAP-SUBP-2" in text


def test_generate_does_not_scaffold_a_capture_the_splicer_refuses():
    """One site passing the literal "ABC", another the item ABC: the
    generator saw one name, the splicer two different arguments, so the
    scaffolded .cut was refused as UNRESOLVED_CAPTURE_TARGET."""
    source = _LITERAL_VS_ITEM.format(first='"ABC"', second="ABC")
    text = _scaffold(source)
    assert "CAPTURE ARG 1" not in text
    assert "CAPTURE ARG 2 INTO UT-CAP-SUBP-2" in text
    program, surface, context = _context_and_surface(source)
    _, unresolved = plan_captures(program, parse_cut(text), surface, context.lines)
    assert unresolved == []


def _two_site_plans(second: str):
    program, surface, _ = _context_and_surface(_TWO_SITES.format(second=second))
    suite = parse_cut(
        'TESTSUITE "s"\n'
        "\n"
        'TESTCASE "c"\n'
        '    MOCK CALL "SUB"\n'
        "        CAPTURE ARG 2 INTO UT-CAP-SUB-2\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    return plan_captures(program, suite, surface)


def test_the_splicer_synthesizes_one_field_for_items_of_one_layout():
    plans, unresolved = _two_site_plans("WS-OTHER")
    assert unresolved == []
    assert capture_working_storage_lines(plans) == ["01  UT-CAP-SUB-2  PIC 9(3)."]


def test_the_splicer_still_refuses_items_of_different_layouts():
    plans, unresolved = _two_site_plans("WS-WIDE")
    assert plans == []
    assert len(unresolved) == 1
    assert "names different items at different call sites" in unresolved[0]


# Regression: bug hunt round 10 (splicer / export / captures). A `UT-CAP-`
# target for a non-ASCII literal was sized in characters, not the bytes PIC X
# counts; a `UT-CAP-` mirror of `PIC X(9)` was reset with `MOVE ZERO` (the
# repeat count's 9 read as a numeric symbol).
from mockymock.splicer.captures import _declaration_for, _literal_declaration

# --- captures: synthesized field sizing and reset --------------------------


def test_a_non_ascii_literal_capture_is_sized_in_bytes():
    declaration, _ = _literal_declaration("T", '"ÉCOLE"')
    assert declaration == "01  T  PIC X(6)."


def test_a_non_ascii_literal_capture_end_to_end():
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CAPU.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A               PIC X(5).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        '           CALL "SUBX" USING "ÉCOLE" WS-A.\n'
    )
    cut = (
        'TESTSUITE "S"\n\nTESTCASE "one"\n    MOCK CALL "SUBX"\n'
        "        CAPTURE ARG 1 INTO UT-CAP-SUBX-1\n    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    result = parse_cobol(source, filename="capu.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    plans, unresolved = plan_captures(result.ast, parse_cut(cut), surface, lines)
    assert unresolved == []
    assert capture_working_storage_lines(plans) == ["01  UT-CAP-SUBX-1  PIC X(6)."]


def test_an_alphanumeric_capture_whose_repeat_count_has_a_9_resets_to_spaces():
    for picture in ("X(9)", "X(19)", "X(90)"):
        built = _declaration_for("T", {"picture": picture, "usage": "DISPLAY"})
        assert built == (f"01  T  PIC {picture}.", "MOVE SPACES TO T")
    assert _declaration_for("T", {"picture": "9(5)", "usage": "DISPLAY"})[1] == (
        "MOVE ZERO TO T"
    )
    assert _declaration_for("T", {"picture": "ZZ9", "usage": "DISPLAY"})[1] == (
        "MOVE ZERO TO T"
    )
