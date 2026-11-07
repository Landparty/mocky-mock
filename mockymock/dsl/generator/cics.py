"""EXEC CICS (and console ACCEPT) helpers: loop-end replies and the
operand roles that decide which fields a fixture row fills."""

from __future__ import annotations

from mockymock.analysis.loops import loop_exit_literal, loop_guard_words, site_in_loop
from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.fixture_bundle import BoundaryFixture, FieldSpec
from mockymock.dsl.generator._context import ProgramContext, _reply_watched_names
from mockymock.dsl.generator.keys import _unique_prefix
from mockymock.dsl.model import MockCategory

#: The EIBRESP a CICS get-next command answers once nothing is left:
#: ENDFILE (20) for a browse, ITEMERR (26) for a TS queue, QZERO (23) for
#: a TD queue.
_CICS_GET_NEXT_END = {"READNEXT": 20, "READPREV": 20, "READQ TS": 26, "READQ TD": 23}


def _accept_loop_end_lines(
    site: BoundarySite,
    context: ProgramContext | None,
    tally: str | None,
) -> list[str]:
    """An ACCEPT inside a loop whose UNTIL waits for the accepted value
    itself (`PERFORM GET-CARD UNTIL WS-IN = "END"` around `ACCEPT WS-IN`,
    the SYSIN control-card loop): a mock giving the same value on every
    call never ends it, so the scaffold hung until --timeout (issue #263).
    Move the loop's sentinel literal into the target after the first call
    (gated on the tally, so the row's own value is still accepted once),
    or on the first call when no tally name is known. A guard that reads
    the target without a literal to match gets a TODO comment."""
    if context is None or not site.keys or not site_in_loop(site, context.looped):
        return []
    target = site.keys[0].upper()
    if target not in loop_guard_words(site, context.guards):
        return []
    literal = loop_exit_literal(site, context.guards, target)
    if literal is None:
        return [
            f"*> TODO: a loop waits on the value this ACCEPT reads into "
            f"{target} -- end it by hand (e.g. MOCK ACCEPT {target} ROWS "
            f"... TERMINAL ( ... )), or this mock never ends it"
        ]
    # The ACCEPT's own target, subscript/qualifier included: the site key
    # is its bare data-name (issue #311).
    move = f"MOVE {literal} TO {site.accept_target or target}"
    if tally is None:
        return [move]
    return [f"IF {tally} > 1", f"    {move}", "END-IF"]


def _cics_get_next_command(site: BoundarySite) -> str | None:
    """`site`'s key in `_CICS_GET_NEXT_END`, or None. A READQ with no TD
    is a TS queue, CICS's own default."""
    words = (site.match_text or "").upper().split()
    if not words:
        return None
    if words[0] == "READQ":
        return "READQ TD" if "TD" in words[1:2] else "READQ TS"
    return words[0] if words[0] in _CICS_GET_NEXT_END else None


def _cics_loop_end_lines(
    site: BoundarySite,
    context: ProgramContext | None,
    tally: str | None,
) -> list[str]:
    """A READNEXT/READPREV/READQ in a loop whose UNTIL reads the command's
    own RESP field (`PERFORM UNTIL WS-RESP NOT = DFHRESP(NORMAL)`, or a
    flag set from it): a mock answering NORMAL on every call never ends
    the browse, so the scaffold hung until --timeout (issue #316). Report
    ENDFILE / ITEMERR / QZERO after the first call -- gated on the tally,
    so the row is still returned once -- the way `_call_loop_end_lines`
    ends an MQGET loop. Every site the key's MOCK answers is checked (a
    priming READNEXT before the loop is the usual shape); sites needing
    different end replies get a TODO comment instead."""
    if (
        context is None
        or context.surface is None
        or site.category is not (MockCategory.CICS)
    ):
        return []
    key = _unique_prefix(site, context.surface)
    sites = [
        other
        for other in context.surface.boundary_sites
        if other.category is MockCategory.CICS
        and (other.match_text or "").startswith(key)
    ] or [site]
    waits = False
    replies: set[tuple[int, str] | None] = set()
    for other in sites:
        command = _cics_get_next_command(other)
        resp = _cics_resp_names([other.statement])
        if command is None or not resp:
            replies.add(None)
            continue
        replies.add((_CICS_GET_NEXT_END[command], resp[0]))
        if site_in_loop(other, context.looped) and loop_guard_words(
            other, context.guards
        ) & _reply_watched_names(other, {resp[0]}, context):
            waits = True
    if not waits:
        return []
    if len(replies) != 1 or None in replies:
        return [
            f"*> TODO: a loop waits on this command's RESP, but its "
            f"{len(sites)} sites need different end replies -- end the "
            f"loop by hand (e.g. MOCK CICS ... ROWS ... TERMINAL), or this "
            f"mock never ends it"
        ]
    reply = replies.pop()
    assert reply is not None  # one distinct reply, and None was excluded
    move = f"MOVE {reply[0]} TO {reply[1]}"
    if tally is None:
        return [move]
    return [f"IF {tally} > 1", f"    {move}", "END-IF"]


#: CICS options whose operand the command only READS, for every command
#: `_cics_input_operand_names` filters (issue #222). cobol-parser marks every
#: EXEC CICS boundary BIDIRECTIONAL and lays out every resolved operand, so
#: without this a generated mock overwrote what the program had just put in
#: `FROM(rec)` / `SEND TEXT FROM(msg)` with random text -- state the real
#: transaction never touches, recorded as golden by `--record-expectations`.
_CICS_INPUT_OPTIONS = frozenset(
    {
        "FROM",
        "FILE",
        "DATASET",
        "QUEUE",
        "QNAME",
        "MAP",
        "MAPSET",
        "PROGRAM",
        "TRANSID",
        "CHANNEL",
        "CONTAINER",
        "SYSID",
        "REQID",
        "TERMID",
        "INTERVAL",
        "TIME",
        "ABCODE",
        "KEYLENGTH",
        "FROMLENGTH",
        "FROMFLENGTH",
        "CURSOR",
    }
)
#: Commands whose RIDFLD the command updates (a browse, or a generic READ).
_CICS_RIDFLD_OUTPUT_COMMANDS = frozenset({"READ", "READNEXT", "READPREV"})
#: Commands whose LENGTH/FLENGTH the command sets to the length it returned.
_CICS_LENGTH_OUTPUT_COMMANDS = frozenset(
    {
        "READ",
        "READNEXT",
        "READPREV",
        "RECEIVE",
        "READQ",
        "RETRIEVE",
        "GET",
        "CONVERSE",
        "WEB",
    }
)
#: Commands that pass COMMAREA to a program that cannot hand it back.
_CICS_COMMAREA_INPUT_COMMANDS = frozenset({"RETURN", "XCTL"})
#: Commands whose operands are all answers (ASSIGN USERID(x), ADDRESS
#: COMMAREA(ptr), ...): nothing is filtered for them.
_CICS_ALL_OUTPUT_COMMANDS = frozenset({"ASSIGN", "INQUIRE", "ADDRESS", "ASKTIME"})


def _cics_operand_name(value: object) -> str | None:
    """The data name an option's operand text starts with, or None for a
    literal / figurative / empty operand."""
    words = str(value or "").replace("(", " ").split()
    if not words or words[0][0] in "\"'0123456789+-":
        return None
    return words[0].upper()


def _cics_operand_roles(statement: object) -> tuple[set[str], set[str]]:
    """(input-only operand names, other operand names) of one EXEC CICS
    statement -- see `_CICS_INPUT_OPTIONS` and the per-command tables."""
    command = str(getattr(statement, "_cics_command", "") or "").upper()
    options = getattr(statement, "options", None) or {}
    inputs: set[str] = set()
    others: set[str] = set()
    for option, value in options.items():
        name = _cics_operand_name(value)
        if name is None:
            continue
        option = str(option).upper()
        if command in _CICS_ALL_OUTPUT_COMMANDS:
            is_input = False
        elif command == "FORMATTIME":
            is_input = option == "ABSTIME"
        elif option == "RIDFLD":
            is_input = command not in _CICS_RIDFLD_OUTPUT_COMMANDS
        elif option in ("LENGTH", "FLENGTH"):
            is_input = command not in _CICS_LENGTH_OUTPUT_COMMANDS
        elif option == "COMMAREA":
            is_input = command in _CICS_COMMAREA_INPUT_COMMANDS
        else:
            is_input = option in _CICS_INPUT_OPTIONS
        (inputs if is_input else others).add(name)
    return inputs, others


def _cics_fixture_statements(
    fixture: BoundaryFixture, source: ProgramContext | None
) -> list | None:
    """The EXEC CICS statement(s) a CICS fixture stands for: the one on
    the fixture's own line, else every statement its key prefixes. None
    with no program to read them from."""
    surface = source.surface if source is not None else None
    if surface is None:
        return None
    key = " ".join(fixture.key.upper().split())
    cics_sites = [
        site
        for site in surface.boundary_sites
        if site.category is MockCategory.CICS
        and (site.match_text or "").startswith(key)
    ]
    return [site.statement for site in cics_sites if site.line == fixture.line] or [
        site.statement for site in cics_sites
    ]


def _cics_resp_names(statements: list) -> list[str]:
    """The RESP and RESP2 operand names of `statements`, in order, once."""
    names: list[str] = []
    for statement in statements:
        options = getattr(statement, "options", None) or {}
        for option, value in options.items():
            if str(option).upper() not in ("RESP", "RESP2"):
                continue
            name = _cics_operand_name(value)
            if name is not None and name not in names:
                names.append(name)
    return names


def _cics_output_layout(
    fixture: BoundaryFixture, source: ProgramContext | None
) -> list[FieldSpec]:
    """`fixture.layout` without the fields only an input operand of the
    fixture's own EXEC CICS statement(s) names (issue #222): a CICS mock
    writes what the command returns (INTO, SET, RESP, RESP2, a READ's
    LENGTH/RIDFLD, ...), never what it reads (FROM, a WRITE's RIDFLD).
    A field also named by a non-input operand of any statement for this
    key is kept. With no program to read the statements from, nothing is
    filtered."""
    statements = _cics_fixture_statements(fixture, source)
    if statements is None:
        return fixture.layout
    inputs: set[str] = set()
    others: set[str] = set()
    for statement in statements:
        statement_inputs, statement_others = _cics_operand_roles(statement)
        inputs |= statement_inputs
        others |= statement_others
    kept = []
    for spec in fixture.layout:
        parts = set(spec.qualified_name.upper().split("."))
        if parts & inputs and not parts & others:
            continue
        kept.append(spec)
    return kept
