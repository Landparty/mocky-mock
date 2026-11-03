"""Prose explanations for every refusal code this package can emit.

Backs `mockymock explain <CODE>` (see
docs/2026-09-15-cut-editor-intelligence-design.md) and, transitively, the
`mocky-mock-vscode` extension's refusal-code hover (which shells out to
`explain --json`). Kept in one place so the explanation text a user reads
from the CLI and the one an editor tooltip shows can never drift apart.

Coverage is partial *and reported*, the same posture
`dialects/le_signatures.py` uses in the sibling cobol-parser repo: a code
this dict has no entry for is a real gap, surfaced by `explain` naming it
as "not catalogued" rather than silently returning nothing that looks the
same as "this code doesn't exist." `_UNCATALOGUED_CODES_ARE_A_BUG` in
tests/unit/test_refusal_explanations.py cross-checks this dict against
every literal refusal code string actually constructed anywhere in
`mockymock/`, so a new code added to a gate without a matching entry here
fails CI rather than shipping silently unexplained.
"""

from __future__ import annotations

REFUSAL_EXPLANATIONS: dict[str, str] = {
    # --- USE REAL CALL (load-module integration tests,
    # docs/2026-11-01-real-call-integration-design.md).
    "REAL_SOURCE_NOT_FOUND": (
        'A USE REAL CALL "<program>" FROM "<path>" names a file that does '
        "not exist. The path is relative to the .cut file's folder. Point "
        "it at the source of the program the CALL runs."
    ),
    "CONFLICTING_REAL_SOURCE": (
        "Two USE REAL CALL lines name the same program with different "
        "source files. One test binary holds one copy of each program, so "
        "every USE REAL CALL of a program must name the same file."
    ),
    "REAL_PROGRAM_ID_MISMATCH": (
        "The file a USE REAL CALL names declares another PROGRAM-ID than "
        "the CALL's literal, so the CALL would never reach it. Point FROM "
        "at the program's own source."
    ),
    "REAL_SOURCE_UNREADABLE": (
        "The source of a USE REAL CALL program could not be read or its "
        "COPY members could not be expanded. Check the file's encoding and "
        "the --copybook-path folders."
    ),
    # --- UNMOCKED_*: a boundary is reachable but no MOCK directive matches
    # it. Every one of these has a mechanical fix -- see
    # RefusalReason.suggested_fix / `generate --fill`.
    "UNMOCKED_CALL": (
        "A static or dynamic CALL is reachable from this test case's "
        "PERFORM target, but no MOCK CALL/MOCK MQ directive names it -- "
        "the call has nowhere to link inside the sandbox. Add a MOCK CALL "
        '"<name>" (or MOCK CALL <identifier> for a dynamic call) block.'
    ),
    "FALLTHROUGH_BOUNDARY": (
        "A warning, not a refusal. The boundary is reachable from this "
        "test case only by falling off the end of a paragraph some GO TO "
        "jumps to -- a conservative path that most runs never take -- so "
        "no MOCK is required for it. It is never executed for real: if a "
        "case does reach it, that case fails with 'unmocked ... boundary "
        "reached'. Add a MOCK only for a case that is meant to go there."
    ),
    "UNMOCKED_FILE_OP": (
        "A file operation (OPEN/CLOSE/READ/WRITE/REWRITE/DELETE/START/"
        "UNLOCK, or a plain-file-form SORT/MERGE/RELEASE/RETURN) is "
        "reachable but no MOCK directive names the file -- it would hit a "
        "file that does not exist in the sandbox. Add a MOCK <VERB> "
        "<file-name> block."
    ),
    "UNMOCKED_SQL": (
        "An EXEC SQL statement is reachable but no MOCK SQL directive "
        "matches its text -- there is no DB2 instance in the sandbox, so "
        "an unmocked EXEC SQL cannot compile/run. Add a MOCK SQL "
        '"<prefix>" block (the prefix is the shortest unique word-run of '
        "the statement's own text)."
    ),
    "UNMOCKED_CICS": (
        "An EXEC CICS command is reachable but no MOCK CICS directive "
        "matches it -- there is no CICS region in the sandbox. Add a MOCK "
        'CICS "<prefix>" block.'
    ),
    "UNMOCKED_DLI": (
        "An EXEC DLI (or CBLTDLI) call is reachable but no MOCK DLI "
        "directive matches it -- there is no IMS DL/I database in the "
        'sandbox. Add a MOCK DLI "<prefix>" block.'
    ),
    "UNMOCKED_CONSOLE_ACCEPT": (
        "An interactive ACCEPT (no FROM clause, or FROM CONSOLE/SYSIN) is "
        "reachable but nothing mocks it -- under a test runner it would "
        "read whatever stdin happens to be attached, or block. Add a MOCK "
        "ACCEPT <target> block."
    ),
    "UNMOCKED_REPORT_WRITER": (
        "An INITIATE/GENERATE/TERMINATE Report Writer statement is "
        "reachable but no MOCK directive names its report -- the RD/FD "
        "stay declared but the report file is never touched by a real "
        'run. Add a MOCK INITIATE/GENERATE/TERMINATE "<report-name>" '
        "block."
    ),
    # --- Structural / whole-program refusals: no mock category exists for
    # these constructs at all.
    "UNSUPPORTED_DECLARATIVES": (
        "The program's DECLARATIVES hold a USE procedure mockymock cannot "
        "run under mocks: USE BEFORE REPORTING (Report Writer GENERATE is "
        "mocked whole, so it would never run), or a USE AFTER EXCEPTION "
        "naming no file or open mode it can place. USE AFTER EXCEPTION/ERROR "
        "procedures on files or open modes are supported: a mocked file "
        "statement whose outcome is an exception PERFORMs the one that "
        "applies, and USE FOR DEBUGGING procedures stay off, as in a "
        "production run."
    ),
    "UNSUPPORTED_ALTER": (
        "The program ALTERs a paragraph mockymock cannot restore between "
        "test cases: one that is not a single plain GO TO, or a GO TO with "
        "no target and no paragraph after it. Other ALTERs run real, and "
        "every case starts with the GO TOs as written."
    ),
    "UNSUPPORTED_SORT_MERGE": (
        "A SORT/MERGE whose shape the grammar does not allow: both an "
        "INPUT/OUTPUT PROCEDURE pair and a USING/GIVING file, so neither "
        "side can be told apart from the other. A plain-file SORT/MERGE "
        "(USING ... GIVING ...) and a mixed one (a file on one side, a "
        "procedure on the other) are mocked with MOCK SORT/MOCK MERGE; a "
        "SORT with both procedures is left real, with its RELEASE/RETURN "
        "mocked."
    ),
    "UNSUPPORTED_NESTED_PROGRAM": (
        "The compilation unit holds an object-oriented CLASS-ID with its "
        "FACTORY/OBJECT/METHOD-ID units, which mockymock does not test. "
        "Nested and stacked PROGRAM-IDs are tested through the outermost "
        "program, with a CALL to a contained program mocked like any CALL."
    ),
    "UNSUPPORTED_CICS_MACRO": (
        "A DFHVALUE(...) macro call, or a DFHRESP(...) call mockymock "
        "could not expand, sits in ordinary COBOL (outside any EXEC block). "
        "DFHRESP(<condition>) on one line is expanded to its EIBRESP number "
        "automatically; what refuses is DFHVALUE (no built-in CVDA table), "
        "a condition name not in the table, or a call split across lines. "
        "Putting the call on one line, or replacing DFHVALUE(X) with its "
        "numeric CVDA value, is usually the fix."
    ),
    "UNSUPPORTED_CICS_DFHCOMMAREA": (
        "DFHCOMMAREA is referenced in the program's text but has no "
        "matching LINKAGE SECTION declaration mockymock can find -- its "
        "size/layout is unknowable, so no storage can be synthesized for "
        "it, however unreachable its references are. Declare DFHCOMMAREA "
        "properly in the LINKAGE SECTION."
    ),
    "UNSUPPORTED_LINKAGE_LAYOUT": (
        "A LINKAGE SECTION item mockymock needs to synthesize storage for "
        "(to satisfy a CALL/ENTRY parameter) has a layout mockymock's "
        "linkage plan cannot resolve. See the message for the specific "
        "item and layout problem."
    ),
    "UNSUPPORTED_LINKAGE_ADDRESSING": (
        "A SET ADDRESS OF statement targets a LINKAGE SECTION item in a "
        "shape mockymock's address-of redirection cannot rewrite safely. "
        "See the message for the specific statement."
    ),
    "UNSUPPORTED_PERFORM_THRU": (
        "A PERFORM ... THRU range (in the test case's own PERFORM line, "
        "or inside the program itself) could not be safely expanded: the "
        "endpoint names 0 or more than 1 paragraph/section, or the range "
        "runs backwards. mockymock refuses rather than guess which slice "
        "of the PROCEDURE DIVISION is meant."
    ),
    "UNSUPPORTED_TERMINATOR_LAYOUT": (
        "A STOP RUN, GOBACK or EXIT PROGRAM, or an EXEC CICS RETURN/"
        "XCTL/ABEND (which never give control back), sits in a shape "
        "mockymock's terminator "
        "neutralization cannot safely rewrite (so the suite's later test "
        "cases would never run). One narrow SECTION-scoped shape (a "
        "section's first paragraph, entered exclusively via PERFORM "
        "<section-name>) is supported instead of refused -- see "
        "docs/2026-07-10-section-scoped-terminator-support-design.md."
    ),
    "UNSUPPORTED_NESTED_MOCK_TARGET": (
        "A MOCK directive matches a statement nested inside an IF/"
        "EVALUATE/inline PERFORM body that mockymock cannot safely "
        "splice (no validated replacement span exists for it) -- "
        "splicing it could swallow a block terminator and corrupt "
        "control flow. Move the statement to the top level of its "
        "paragraph, or mock the whole paragraph/section instead (MOCK "
        "PARAGRAPH/MOCK SECTION)."
    ),
    "CONDITION_NAME_MISMATCH": (
        "A .cut line treats a level-88 condition-name as a value, or a "
        "plain data item as a condition: EXPECT <item> TO BE TRUE on an "
        "item that is not an 88, or EXPECT <88> TO BE <value>. cobc would "
        "reject the generated driver. A condition-name is only ever TRUE "
        "or FALSE; any other item is compared with a value."
    ),
    "UNSUPPORTED_CICS_CONDITION": (
        "A MOCK CICS body says CONDITION IS <name>, but where the mocked "
        "command would send that condition cannot be told: no EXEC CICS "
        "HANDLE CONDITION label is in force for it (the real command would "
        "take the system default action, usually an abend), the command is "
        "written with RESP or NOHANDLE (HANDLE does not apply -- set the "
        "RESP field in the mock body instead), or the program uses PUSH/POP "
        "HANDLE, whose runtime stack mockymock does not model."
    ),
    "UNSUPPORTED_CICS_HANDLE": (
        "An EXEC CICS HANDLE CONDITION or IGNORE CONDITION could not be "
        "read. mockymock emulates it (spliced to CONTINUE, its labels "
        "followed when a mock raises a condition), so one it cannot read "
        "can neither be emulated nor dropped without changing control flow."
    ),
    "UNKNOWN_DATA_NAME": (
        "A MOVE target, EXPECT data-name, CAPTURE INTO target or bare-word "
        "value in the .cut names nothing the program declares -- cobc "
        "would reject the generated driver. Fix the spelling, or quote the "
        'value if it is meant as text (TO BE "Y", not TO BE Y).'
    ),
    "UNSUPPORTED_SOURCE_FORMAT": (
        "The program is free-format COBOL. mockymock edits and compiles "
        "fixed-format source only (code in columns 8-72), so a free-format "
        "program would be cut apart before cobc ever saw it. Convert the "
        "program to fixed format to test it."
    ),
    "UNSUPPORTED_MOCK_TARGET_LAYOUT": (
        "A MOCK directive matches a top-level statement that shares a "
        "source line with other code (sibling code before it, a one-line "
        "paragraph header, or another statement after it) -- splicing it "
        "would comment out that sibling code along with it. Put the "
        "statement on its own line(s)."
    ),
    "MOCK_LINE_TOO_LONG": (
        "A MOCK body line is copied into the test program as written, and "
        "GnuCOBOL truncates a free-format source line past 512 bytes, so "
        "the build would fail with syntax errors that never mention the "
        "truncation. A `MOVE <one long literal> TO <field>` is split "
        "automatically; break any other long statement across several "
        "lines of the mock body."
    ),
    "UNLIFTABLE_CLAUSE_BODY": (
        "A MOCK directive matches a READ / RETURN / WRITE / REWRITE / "
        "DELETE / START / CALL whose AT END / INVALID KEY / ON EXCEPTION "
        "(or NOT ...) bodies cannot be re-run after the mock: one holds "
        "GOBACK, STOP RUN, EXIT PROGRAM, ALTER, NEXT SENTENCE, CANCEL or "
        "another boundary statement, a clause mockymock cannot guard "
        "(AT END-OF-PAGE), a nested conditional phrase not closed by its "
        "own END-<verb>, or an IF left open before the next clause. "
        "Splicing the mock replaces the whole statement, so every body "
        "would be deleted with it. Move that code out of the clause -- set "
        "a flag in it and act on the flag after the statement."
    ),
    "UNSUPPORTED_FLOW_MOCK_TARGET": (
        "A MOCK PARAGRAPH/MOCK SECTION names this test case's own PERFORM "
        "entry point. Mocking the entry point would replace the very "
        "code the test performs, leaving nothing to test. PERFORM a "
        "caller of it instead, and mock the target from there."
    ),
    "UNSUPPORTED_INVOKE": (
        "An INVOKE method call on an object reference is an external "
        "dependency mockymock has no mock category for (object-oriented "
        "COBOL is outside the GnuCOBOL toolchain mockymock compiles "
        "with). Isolate the paragraph with MOCK PARAGRAPH, or PERFORM a "
        "caller whose flow never reaches it."
    ),
    "UNSUPPORTED_CHAIN": (
        "CHAIN transfers control to another program without returning (a "
        "Micro Focus extension). mockymock cannot mock it the way it "
        "mocks CALL, since nothing after it in the test case would run. "
        "Isolate the paragraph with MOCK PARAGRAPH, or PERFORM a caller "
        "whose flow never reaches it."
    ),
    "UNSUPPORTED_COMMUNICATION": (
        "SEND/RECEIVE/ENABLE/DISABLE/PURGE go through the COBOL-85 "
        "Communication Module's message control system -- an external "
        "message queue mockymock has no mock category for. Isolate the "
        "paragraph with MOCK PARAGRAPH, or PERFORM a caller whose flow "
        "never reaches it."
    ),
    "UNSUPPORTED_STOP_LITERAL": (
        "STOP <literal> waits for the operator on the console. mockymock "
        "answers it at once (the statement becomes CONTINUE), except "
        "inside another boundary statement's clause body (a CALL's ON "
        "EXCEPTION, a READ's AT END). Move it out of the clause, or "
        "isolate the paragraph with MOCK PARAGRAPH."
    ),
    "UNSUPPORTED_SCREEN_DISPLAY": (
        "A screen DISPLAY (AT, LINE, COLUMN, attributes, UPON CRT) would "
        "switch GnuCOBOL to screen mode and hide the test results. "
        "mockymock answers it with CONTINUE, except inside another "
        "boundary statement's clause body. Move it out of the clause, or "
        "isolate the paragraph with MOCK PARAGRAPH."
    ),
    "UNSUPPORTED_STATEMENT": (
        "mockymock does not model this statement at all: it is neither a "
        "known pass-through (touches nothing outside the program) nor a "
        "mockable boundary, so its effects cannot be verified or mocked -- "
        "fail closed rather than assume it is side-effect free. Isolate "
        "the paragraph with MOCK PARAGRAPH, or PERFORM a caller whose "
        "flow never reaches it."
    ),
    "UNSUPPORTED_PHANTOM_PARAGRAPH": (
        "A paragraph is named exactly END-ADD/END-SUBTRACT/END-MULTIPLY/"
        "END-DIVIDE/END-COMPUTE -- reserved arithmetic scope-terminator "
        "words the pinned cobol-parser version fails to consume as their "
        "statement's own scope terminator when written alone on a line, "
        "instead parsing them as paragraph names and silently reparenting "
        "every following statement. This is a defense-in-depth guard for "
        "an upstream cobol-parser limitation, not something to work "
        "around in the .cut file -- rename the paragraph if it is "
        "genuinely meant as one, or wait for the upstream fix."
    ),
    "UNSUPPORTED_DATA_DIVISION_EXEC": (
        "A DATA DIVISION EXEC SQL construct (typically a second, live "
        "EXEC SQL INCLUDE found while re-scanning already-spliced "
        "content, or an unrecognized DATA DIVISION EXEC SQL like "
        "WHENEVER) is in a shape mockymock's SQLCA synthesis does not "
        "support, or shares a source line with sibling content that "
        "splicing it would delete."
    ),
    # --- Per-directive / per-test-case authoring mistakes.
    "AMBIGUOUS_MOCK": (
        "Two or more MOCK directives in this test case match the same "
        "physical boundary site. mockymock fails closed rather than "
        "guess which one you meant -- make the directives' keys "
        "unambiguous (a more specific file/CALL name, or a longer SQL/"
        "CICS/DLI text prefix)."
    ),
    "UNMATCHED_MOCK": (
        "A MOCK (or VERIFY) directive in this test case doesn't match "
        "any boundary site actually reachable from its PERFORM target -- "
        "typically a typo'd key, or a mock written for a paragraph this "
        "test case doesn't reach. Check the key spelling and the "
        "PERFORM target."
    ),
    "VERIFY_WITHOUT_MOCK": (
        "A VERIFY directive names a (category, key) this test case has "
        "no matching MOCK directive for -- its tally counter would be "
        "undeclared or stale. Add the matching MOCK block, or fix the "
        "VERIFY's own key."
    ),
    "UNMOCKABLE_ACCEPT_SOURCE": (
        "A MOCK ACCEPT directive targets an ACCEPT ... FROM <system "
        "source> (COMMAND-LINE, ENVIRONMENT, ARGUMENT-VALUE, ...) that "
        "GnuCOBOL resolves internally rather than reading a console -- "
        "there is nothing for a mock to intercept. These are deliberately "
        "not boundary sites; remove the MOCK ACCEPT for this target. (FROM "
        "DATE / TIME / DAY / DAY-OF-WEEK are the exception: a MOCK ACCEPT "
        "naming one gives the test a fixed clock.)"
    ),
    "UNRESOLVED_FILE_STATUS_TARGET": (
        "A MOCK directive uses FILE-STATUS IS, but the named file has no "
        "FILE STATUS IS <field> clause in its SELECT entry -- there is "
        "no WORKING-STORAGE field to move the status into. Add a FILE "
        "STATUS clause to the file's SELECT entry, or drop FILE-STATUS IS "
        "from the mock."
    ),
    "CAPTURE_ARG_OUT_OF_RANGE": (
        "A CAPTURE ARG <n> INTO ... names an argument position the real "
        "CALL statement doesn't have that many USING parameters for -- "
        "checked against every matching site program-wide (not just "
        "reachable ones), so it refuses even if only one of several "
        "sites sharing the mocked key is too narrow. Also refused when "
        "that position is OMITTED at any matching site (`USING OMITTED "
        "B`): nothing is passed there to capture. Fix the argument "
        "number."
    ),
    "AMBIGUOUS_PARAGRAPH": (
        "A paragraph this test case can reach shares its name with a "
        "paragraph in another SECTION. COBOL resolves such a name by "
        "section, but mockymock resolves paragraphs by name alone, so it "
        "cannot tell which body runs or which boundaries the case "
        "reaches -- a CALL only the other body makes would run for real. "
        "Refused rather than guessed; rename the paragraphs so each name "
        "is unique in the program."
    ),
    "UNKNOWN_PARAGRAPH": (
        "A test case's own PERFORM target (or a driver-side PERFORM ... "
        "THRU endpoint) does not name a real paragraph or section in the "
        "PROCEDURE DIVISION -- almost always a typo. Check the spelling "
        "against the program's own paragraph names."
    ),
    "UNRESOLVED_FLOW_TARGET": (
        "A PERFORM/GO TO target, or an XML PARSE PROCESSING PROCEDURE, "
        "names something the reachability analysis cannot resolve to a "
        "real paragraph or section (an unparsed target, or a construct "
        "the pinned cobol-parser release only keeps as text). Fails "
        "closed rather than guess the control-flow edge."
    ),
    "UNRESOLVED_FLOW_MOCK_TARGET": (
        "A MOCK PARAGRAPH/MOCK SECTION names no paragraph or section in "
        "the PROCEDURE DIVISION, names more than one (an ambiguous name), "
        "or names the other kind (MOCK PARAGRAPH on a SECTION, or the "
        "reverse). Check the spelling, and use the keyword that matches "
        "how the program declares it."
    ),
    "UNRESOLVED_CAPTURE_TARGET": (
        "A CAPTURE ARG <n> INTO UT-CAP-... target cannot be declared for "
        "you: the argument's layout cannot be mirrored exactly by a "
        "synthesized field (a table, a PICTURE-less COMP-1/POINTER item, "
        "a group holding binary data), the argument is a literal or not a "
        "uniquely named item, the name is already declared by the "
        "program, or one target is captured from arguments of different "
        "layouts. Capture into a WORKING-STORAGE item of your own instead."
    ),
    "UNSAVABLE_BEFORE_ALL_STATE": (
        "The .cut has BEFORE-ALL steps, so every test case must start from "
        "the state those steps leave behind -- mockymock saves each "
        "WORKING-STORAGE, LOCAL-STORAGE and record item right after "
        "BEFORE-ALL and restores it before each case. The named item "
        "cannot be saved exactly: a group holding an OCCURS ... DEPENDING "
        "ON table (its size at restore time depends on a counter the "
        "restore overwrites), a table whose bound cannot be read, or an "
        "item whose description cannot be reproduced. Move the steps to "
        "BEFORE-EACH, which runs before every case and needs no saved "
        "state."
    ),
    "COLUMN_OVERFLOW": (
        "mockymock export could not fit an instrumented line within "
        "column 72, the fixed-format limit a mainframe compiler enforces "
        "-- most often a MOCK body statement, which is re-indented when "
        "it is spliced in. Shorten that statement in the .cut (split it, "
        "or use shorter identifiers) and export again."
    ),
    # --- Whole-program parse/expansion gates (not per-test-case).
    "PARSE_ERROR": (
        "cobol-parser reported one or more hard parse errors on the "
        "program -- the AST could not be built at all. Fix the reported "
        "syntax errors in the COBOL source; mockymock cannot analyze or "
        "test a program that doesn't parse."
    ),
    "PARSE_WARNING": (
        "The parse succeeded but cobol-parser's own ParseResult.warnings "
        "reports dropped statements -- the AST is missing content, so "
        "any scaffold or reachability analysis built from it would "
        "silently miss boundaries. Usually caused by an unresolved COPY "
        "or an unsupported construct upstream in cobol-parser."
    ),
    "EXPANSION_WARNING": (
        "Copybook expansion produced a lossy decode (an encoding warning "
        "on one of the expanded members) -- the expanded text may be "
        "corrupted. Refused before the corrupted text is ever parsed. "
        "Check the copybook's actual encoding against what "
        "--copybook-path / the auto-detector assumed."
    ),
    "UNRESOLVED_COPYBOOK": (
        "A COPY statement (or EXEC SQL INCLUDE) could not be resolved "
        "against the given --copybook-path directories -- without "
        "expansion the referenced fields don't exist, so a scaffold or "
        "test run built from the unexpanded source would be silently "
        "wrong. Pass the copybook's real location with --copybook-path."
    ),
    "DYNAMIC_CALL": (
        "A dynamic CALL's target identifier could not be determined by "
        "cobol-parser's static analysis (it could not resolve what value "
        "the identifier holds) -- dynamic CALLs are only mockable "
        "through their identifier (MOCK CALL <identifier>), and without "
        "a captured identifier there's no key to mock."
    ),
    "UNMOCKED_CANCEL": (
        "A CANCEL is reachable, but the same program name isn't covered "
        "by a MOCK CALL/MOCK CALL <identifier> in this test case. CANCEL "
        "is only a safe no-op when every CALL for the same program is "
        "mocked (the module is then never really loaded) -- add the "
        "matching MOCK CALL for the CANCELed program name(s)."
    ),
    "NESTED_EXEC": (
        "An EXEC SQL/CICS/DLI block sits nested inside a conditional/"
        "loop body and cannot be stubbed out safely there -- every EXEC "
        "block must be stubbed for GnuCOBOL to compile the program at "
        "all (it has no SQL/CICS/DLI precompiler), and no validated "
        "replacement span exists for this nested one. Move it to the "
        "top level of its paragraph."
    ),
    "UNSPLICEABLE_EXEC": (
        "An EXEC SQL/CICS/DLI block shares a source line with sibling "
        "code -- stubbing it out (required for GnuCOBOL to compile, "
        "since it has no precompiler) would comment out that sibling "
        "code too. Put the EXEC block on its own line(s)."
    ),
    "UNSUPPORTED_SQL_WHENEVER": (
        "An EXEC SQL WHENEVER is not in a form mockymock can emulate. "
        "WHENEVER is a precompiler declaration: mockymock replaces it and "
        "puts the precompiler's own `IF SQLCODE ... GO TO <paragraph>` "
        "check after every later mocked SQL statement, for SQLERROR, "
        "SQLWARNING and NOT FOUND with CONTINUE or GO TO <paragraph>. Any "
        "other shape is refused rather than dropped, since dropping it "
        "would run different control flow than DB2 does."
    ),
}
