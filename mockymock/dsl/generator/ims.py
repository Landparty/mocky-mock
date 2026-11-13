"""IMS DL/I (CBLTDLI/CEETDLI) and looped-CALL end-of-data replies."""

from __future__ import annotations

import re
from dataclasses import replace

from mockymock.analysis.loops import (
    flag_branch_comparisons,
    loop_control_words,
    loop_guard_words,
    site_in_loop,
)
from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.fixture_bundle import BoundaryFixture
from mockymock.dsl.generator._context import ProgramContext, _reply_watched_names
from mockymock.dsl.generator.keys import _unique_prefix
from mockymock.dsl.model import MockCategory

#: DL/I get-next calls and the DIBSTAT each returns once nothing is left:
#: GB (end of database) for GN/GHN, GE (no more under this parent) for the
#: within-parent forms.
_DLI_GET_NEXT_END = {"GN": "GB", "GHN": "GB", "GNP": "GE", "GHNP": "GE"}


def _dli_loop_end_lines(
    site: BoundarySite,
    context: ProgramContext | None,
    tally: str | None,
) -> list[str]:
    """A get-next DL/I call in a loop, in a program that tests DIBSTAT:
    an empty mock body leaves DIBSTAT blank ("found") on every call, so a
    `PERFORM UNTIL` scan never ends (EXECDLI, found with #145). Report the
    end status after the first call -- with a tally, so one segment is
    still returned -- or on the first call when no tally name is known.

    Every site the key's MOCK answers is checked, not just `site` (issue
    #315): the standard shape primes the loop with an identical GN before
    it, and that priming site -- the first one seen -- is not itself in a
    loop."""
    if context is None or not context.references("DIBSTAT"):
        return []
    words = (site.match_text or "").split()
    end_status = _DLI_GET_NEXT_END.get(words[0].upper()) if words else None
    if end_status is None:
        return []
    sites = [site]
    if context.surface is not None:
        key = _unique_prefix(site, context.surface)
        sites += [
            other
            for other in context.surface.boundary_sites
            if other.category is MockCategory.DLI
            and (other.match_text or "").startswith(key)
        ]
    if not any(site_in_loop(other, context.looped) for other in sites):
        return []
    if tally is None:
        return [f'MOVE "{end_status}" TO DIBSTAT']
    return [
        f"IF {tally} > 1",
        f'    MOVE "{end_status}" TO DIBSTAT',
        "END-IF",
    ]


#: CALL-level DL/I interfaces whose USING list is (function, PCB, ...).
_DLI_CALL_INTERFACES = frozenset({"CBLTDLI", "CEETDLI"})

#: The PCB status a DL/I call reports once nothing more matches: GB (end of
#: database) for an unqualified get-next, GE (not found) for the rest.
_DLI_CALL_END = {
    "GU": "GE",
    "GHU": "GE",
    "GN": "GB",
    "GHN": "GB",
    "GNP": "GE",
    "GHNP": "GE",
}


def _dli_success_reply(body: list[str], site: BoundarySite) -> list[str]:
    """`body` plus a blank PCB status for a CBLTDLI/CEETDLI call: the
    status DL/I reports for a call that found (or stored) its segment,
    at bytes 11-12 of the PCB, the call's second USING argument. The
    fixture row is random, so without this it handed the first call a
    non-blank status such as "PO" and a `PERFORM UNTIL PCB-STATUS NOT =
    SPACES` get loop ended before it started (issue #317, the DL/I
    counterpart of #205). The end-of-data reply `_call_loop_end_lines`
    adds after this still wins on the call that ends the loop."""
    if site.category is not MockCategory.CALL or not site.keys:
        return body
    if site.keys[0].upper() not in _DLI_CALL_INTERFACES:
        return body
    using = list(getattr(site.statement, "using_parameters", None) or [])
    names = [str(getattr(param, "name", "") or "") for param in using]
    if len(names) < 2 or not names[1]:
        return body
    return body + [f"MOVE SPACES TO {names[1]}(11:2)"]


def _call_end_reply(
    site: BoundarySite, context: ProgramContext
) -> tuple[tuple[tuple[str, str], ...], set[str]] | None:
    """The reply a real MQGET or DL/I get call gives once there is nothing
    left to return, as (value, target) MOVEs, plus the argument names that
    reply is written to -- or None when `site` is no such call.

    MQGET answers MQCC_FAILED (2) with MQRC_NO_MSG_AVAILABLE (2033) in its
    CompCode/Reason arguments (8th and 9th). A CBLTDLI/CEETDLI get call
    puts its status at bytes 11-12 of every DB PCB (after the 8-byte DBD
    name and 2-byte level), whatever the program named that field."""
    using = list(getattr(site.statement, "using_parameters", None) or [])
    names = [str(getattr(param, "name", "") or "") for param in using]
    key = site.keys[0].upper() if site.keys else ""
    if key == "MQGET":
        if len(names) < 9 or not names[7] or not names[8]:
            return None
        return (("2", names[7]), ("2033", names[8])), {names[7], names[8]}
    if key in _DLI_CALL_INTERFACES:
        if len(names) < 2 or not names[0] or not names[1]:
            return None
        function = _dli_function(names[0], context).strip().upper()
        if _is_message_pcb(names[1], context):
            end_status = _DLI_MESSAGE_END.get(function)
        else:
            end_status = _DLI_CALL_END.get(function)
            if end_status is not None:
                end_status = (
                    _dli_guard_end_status(site, names[1], function, context)
                    or end_status
                )
        if end_status is None:
            return None
        return ((f'"{end_status}"', f"{names[1]}(11:2)"),), {names[1]}
    return None


def _dli_guard_end_status(
    site: BoundarySite, pcb: str, function: str, context: ProgramContext
) -> str | None:
    """The not-found status a loop of the program waits for on `pcb`'s
    status field (`PERFORM UNTIL ORD-PCB-STATUS = 'GE'`), when every such
    loop names the same one. Whether a get-next ends with GB or GE depends
    on its SSAs, which the generator does not evaluate: a qualified GN
    reports GE at the end of its range, so the default GB never satisfied
    that guard and the run spun until the timeout (2026-11-03, IMSORDER).
    A loop on a flag (`UNTIL AT-END-OF-DB`) set in a branch on the status
    (`IF PCB-STATUS-CODE = 'GE'  MOVE 'Y' TO WS-EOF`) counts too
    (IMSPATIE), and so does a loop on a level-88 of the status field
    itself (`88 IO-NO-MORE VALUE 'QC'`, `UNTIL IO-NO-MORE`).

    A GU also accepts QC, the message queue's end: `_is_message_pcb` only
    knows an I/O PCB by a three-argument ISRT through it, which misses an
    ISRT that passes an MFS MOD name and a reply sent through an ALT PCB.
    The GU was then answered GE, which an `UNTIL IOPCB-STATUS = 'QC'` loop
    never sees, and the run spun until the timeout (2026-11-13 benchmark,
    7 IMS MPPs). A GN likewise accepts QD: a GN on the I/O PCB reads the
    next segment of a multi-segment message, and `_is_message_pcb` takes
    any PCB read with a get-next for a database PCB, so the GN was
    answered GB and an `UNTIL IOPCB-STATUS = 'QD'` loop never ended."""
    watched = context.names_under(pcb)
    flags: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for guard in context.guards:
        pairs += _STATUS_COMPARE_RE.findall(guard.until_text.upper())
        for word in guard.words:
            owners = context.condition_owners(word)
            flags |= {word} | owners
            value = context.literal_value(word) if owners & watched else None
            if value is not None:
                pairs += [(owner, value.strip()) for owner in owners & watched]
    statements = context.paragraph_statements(site.paragraph_name)
    pairs += [
        (name, literal.strip("'\""))
        for name, literal in flag_branch_comparisons(statements, watched, flags)
    ]
    accepted = _DLI_NOT_FOUND | (
        {_DLI_MESSAGE_END[function]} if function in _DLI_MESSAGE_END else set()
    )
    found = {status for name, status in pairs if name in watched and status in accepted}
    return found.pop() if len(found) == 1 else None


_STATUS_COMPARE_RE = re.compile(
    r"([\w-]+)\s*(?:=|(?:IS\s+)?EQUALS?(?:\s+TO)?)\s*[\"']([A-Z]{2})[\"']"
)


#: The DL/I statuses that mean nothing more was found.
_DLI_NOT_FOUND = frozenset({"GE", "GB"})


#: The status a message call reports on the I/O PCB once nothing is left:
#: QC for a GU (no more messages on the queue), QD for a GN (no more
#: segments in this message, the end of a multi-segment input message).
_DLI_MESSAGE_END = {"GU": "QC", "GN": "QD"}

#: Get-next calls: a PCB read with one of them is taken for a database PCB
#: (a GN loop over segments), even when the program also ISRTs through it.
_DLI_GET_NEXT_CALLS = frozenset({"GN", "GHN", "GNP", "GHNP"})

#: DL/I calls only a message (I/O or alternate) PCB takes. ISRT counts only
#: with exactly three arguments (function, PCB, message): a database ISRT
#: always names its segment in at least one SSA.
_DLI_MESSAGE_ONLY_CALLS = frozenset({"PURG", "CHNG"})


def _dli_function(argument: str, context: ProgramContext) -> str:
    """The DL/I function code a CBLTDLI/CEETDLI call's first argument
    holds: the literal itself, or the VALUE literal of the item it names,
    else the name as written (which matches no known function)."""
    from mockymock.splicer.injector import _literal_inner, reported_literal

    quoted = reported_literal(argument)
    if quoted is not None:
        return _literal_inner(quoted)
    return context.literal_value(argument) or argument


def _dli_sites(context: ProgramContext) -> list[tuple[BoundarySite, list[str]]]:
    """Every CBLTDLI/CEETDLI CALL site of the program with its USING names."""
    sites = []
    for site in context.surface.boundary_sites if context.surface else []:
        if site.category is not MockCategory.CALL or not site.keys:
            continue
        if site.keys[0].upper() not in _DLI_CALL_INTERFACES:
            continue
        using = list(getattr(site.statement, "using_parameters", None) or [])
        sites.append((site, [str(getattr(p, "name", "") or "") for p in using]))
    return sites


def _is_message_pcb(pcb: str, context: ProgramContext) -> bool:
    """True when the program sends a message through `pcb` (a three-argument
    ISRT, or a PURG/CHNG) and never reads it with a get-next: it is then an
    I/O PCB, whose GU loop ends on QC ("no more messages"), never on a
    database PCB's GE. Without this the scaffold of an IMS MPP ended its GU
    loop with GE, which a `UNTIL IOPCB-STATUS = "QC"` loop never sees."""
    wanted = pcb.upper()
    sends = False
    for _, names in _dli_sites(context):
        if len(names) < 2 or names[1].upper() != wanted:
            continue
        function = _dli_function(names[0], context).strip().upper()
        if function in _DLI_GET_NEXT_CALLS:
            return False
        if function in _DLI_MESSAGE_ONLY_CALLS or (
            function == "ISRT" and len(names) == 3
        ):
            sends = True
    return sends


def _row_already_ends(
    body: list[str], site: BoundarySite, context: ProgramContext | None
) -> bool:
    """True when the fixture row itself MOVEs the end-of-data status (2033,
    or the PCB's GB/GE) into the reply field: the loop then ends on the
    first call and the bundle's own count stands."""
    if context is None:
        return False
    if site.keys and site.keys[0].upper() in _DLI_CALL_INTERFACES:
        # `_dli_success_reply` blanks the PCB status after the row's own
        # MOVEs, so no DL/I row ends the loop by itself.
        return False
    reply = _call_end_reply(site, context)
    if reply is None:
        return False
    value, _ = reply[0][-1]
    watched = set().union(*(context.names_under(name) for name in reply[1]))
    for line in body:
        match = re.match(r"MOVE\s+(.+?)\s+TO\s+(\S+)$", line)
        if match and match.group(2).upper() in watched:
            if match.group(1).strip('"').strip() == value.strip('"'):
                return True
    return False


def _call_loop_end_lines(
    site: BoundarySite,
    context: ProgramContext | None,
    tally: str | None,
) -> list[str]:
    """A looped MQGET or DL/I get CALL whose loop waits on the call's own
    reply (`PERFORM UNTIL WS-REASON = 2033`, `UNTIL PCB-STATUS = "GB"`):
    a mock that replays its row on every call never satisfies that guard,
    so the run spins until the executor timeout (issue #156). Report end of
    data after the first call -- with a tally, so the fixture row is still
    returned once -- the way a READ mock reports AT END after its rows.

    One MOCK directive answers every site of its key, so the reply is only
    synthesized when every site would get the same one; a key mixing, say,
    a GU and an ISRT through CBLTDLI gets a TODO comment instead."""
    if context is None or site.category is not MockCategory.CALL or not site.keys:
        return []
    sites = [
        other
        for other in (context.surface.boundary_sites if context.surface else [])
        if other.category is MockCategory.CALL and site.keys[0] in other.keys
    ] or [site]
    replies = [_call_end_reply(other, context) for other in sites]
    watched = [
        reply is not None
        and site_in_loop(other, context.looped)
        and bool(
            loop_guard_words(other, context.guards)
            & _reply_watched_names(other, reply[1], context)
        )
        for other, reply in zip(sites, replies, strict=True)
    ]
    if not any(watched):
        return []
    if any(watched) and not all(
        flag for flag, reply in zip(watched, replies, strict=True) if reply is not None
    ):
        # Only a loop that waits on a call's reply needs the end-of-data
        # status. A get call whose reply no loop reads (an IMS MPP's GU on
        # its DB PCB inside the message loop) keeps the row's own status:
        # answering GE there too would send every case down the not-found
        # path, so the found path and what it calls were never run.
        kept = [
            reply if flag else None
            for flag, reply in zip(watched, replies, strict=True)
        ]
        # Every site that still needs a reply needs the same one. A tally
        # gate alone would also hand it to the other calls of the key after
        # the first (the ISRT, the GU on a database PCB): gate on the
        # function code and PCB then. A priming GN outside the loop that
        # matches the looped GN (issue #317) is the first call, so the
        # tally gate alone is right for it.
        distinct = {reply[0] for reply in kept if reply is not None}
        if len(distinct) == 1:
            if site.keys[0].upper() in _DLI_CALL_INTERFACES and _dli_needs_gate(
                sites, watched, replies, context
            ):
                gated = _dli_end_lines_by_function(site, sites, kept, context, tally)
                if gated is not None:
                    return gated
            replies = [reply for reply in kept if reply is not None]
    if len({reply[0] if reply else None for reply in replies}) != 1:
        gated = _dli_end_lines_by_function(site, sites, replies, context, tally)
        if gated is not None:
            return gated
        return [
            f"*> TODO: a loop waits on this CALL's reply, but its "
            f"{len(sites)} sites need different end-of-data replies -- "
            f"end the loop by hand (e.g. MOCK CALL ... ROWS ... TERMINAL), "
            f"or this mock never ends it"
        ]
    first = replies[0]
    assert first is not None  # one distinct reply, and some site has one
    moves = [f"MOVE {value} TO {target}" for value, target in first[0]]
    if tally is None:
        return moves
    return [f"IF {tally} > 1", *(f"    {move}" for move in moves), "END-IF"]


def _dli_needs_gate(
    sites: list[BoundarySite],
    watched: list[bool],
    replies: list[tuple[tuple[tuple[str, str], ...], set[str]] | None],
    context: ProgramContext,
) -> bool:
    """Whether the key has a call the end-of-data reply must skip that is
    not simply the first call: a non-get call (ISRT, REPL) or a get call
    whose function code and PCB no looped call shares."""

    def call_of(other: BoundarySite) -> tuple[str, str]:
        using = list(getattr(other.statement, "using_parameters", None) or [])
        function = _dli_function(str(using[0].name), context) if using else ""
        pcb = str(using[1].name) if len(using) > 1 else ""
        return function.strip().upper(), pcb.upper()

    looped = {
        call_of(other) for other, flag in zip(sites, watched, strict=True) if flag
    }
    return any(
        reply is None or call_of(other) not in looped
        for other, flag, reply in zip(sites, watched, replies, strict=True)
        if not flag
    )


def _dli_end_lines_by_function(
    site: BoundarySite,
    sites: list[BoundarySite],
    replies: list[tuple[tuple[tuple[str, str], ...], set[str]] | None],
    context: ProgramContext,
    tally: str | None,
) -> list[str] | None:
    """The end-of-data reply of a CBLTDLI/CEETDLI key whose sites need
    different ones (an IMS MPP's GU loop and its ISRT reply through one
    `MOCK CALL "CBLTDLI"`), each gated on the function code the call
    passed, read back from the key's scaffolded `CAPTURE ARG 1` (whose
    MOVE runs before the body). None when that cannot be done: not a DL/I
    key, no function-code capture, or a get site whose function code is
    not a literal."""
    if site.keys[0].upper() not in _DLI_CALL_INTERFACES:
        return None
    capture = next(
        (
            line.split(" INTO ", 1)[1].strip()
            for line in context.captures_for(MockCategory.CALL, site.keys[0])
            if line.upper().startswith("CAPTURE ARG 1 INTO ")
        ),
        None,
    )
    if capture is None:
        return None
    functions: dict[tuple[tuple[str, str], ...], list[str]] = {}
    for other, reply in zip(sites, replies, strict=True):
        if reply is None:
            continue  # ISRT, REPL, ...: answered by the blank status
        using = list(getattr(other.statement, "using_parameters", None) or [])
        function = _dli_function(str(using[0].name), context).strip().upper()
        if function not in _DLI_CALL_END:
            return None
        literal = f'"{function}"'
        if literal not in functions.setdefault(reply[0], []):
            functions[reply[0]].append(literal)
    # The leading comment also keeps the callers from fixing the key's
    # VERIFY count at "row + end reply": the other functions' calls (the
    # ISRT per message) count too, and how many there are is not known.
    lines: list[str] = [
        "*> the end-of-data reply is gated on the DL/I function code, "
        "since one mock answers every call of this key"
    ]
    pcbs_of: dict[str, set[str]] = {}
    for _, names in _dli_sites(context):
        if len(names) >= 2:
            function = _dli_function(names[0], context).strip().upper()
            pcbs_of.setdefault(function, set()).add(names[1].upper())
    for moves, literals in functions.items():
        condition = " OR ".join(f"{capture} = {literal}" for literal in literals)
        if len(literals) > 1:
            condition = f"({condition})"
        shared = any(
            len(pcbs_of.get(literal.strip('"'), ())) > 1 for literal in literals
        )
        target = moves[0][1] if moves else ""
        if shared and target.endswith("(11:2)"):
            # One function on several PCBs (an MPP's message GU and its
            # GU on a database PCB): only the call on the PCB this reply
            # is for ends the loop.
            condition = f'{condition} AND UT-PASSED-ARG-2 = "{target[:-6].upper()}"'
        if tally is not None:
            condition = f"{tally} > 1 AND {condition}"
        lines.append(f"IF {condition}")
        lines.extend(f"    MOVE {value} TO {target}" for value, target in moves)
        lines.append("END-IF")
    return lines


def _without_loop_control(
    fixture: BoundaryFixture,
    site: BoundarySite | None,
    context: ProgramContext | None,
) -> tuple[BoundaryFixture, list[str]]:
    """Drop the fixture fields a CALL/DYNCALL/DLI mock must not write: the
    VARYING / AFTER control items and UNTIL words of the loops `site` runs
    in. `CALL "FMTLINE" USING WS-IX WS-LINE` inside `PERFORM VARYING WS-IX
    ... UNTIL WS-IX > WS-COUNT` passes the counter BY REFERENCE, so the
    bundle lays it out, and a generated `MOVE 0 TO WS-IX` reset the loop on
    every call: the happy path ran until --timeout (issue #286). The
    program advances those items itself; a guard that waits on the call's
    own reply (MQGET / DL/I get, #156) keeps its fields, since the end
    reply is what ends that loop. Returns the trimmed fixture and a TODO
    naming each dropped field."""
    if context is None or site is None or not fixture.layout:
        return fixture, []
    control = loop_control_words(site, context.guards)
    if not control:
        return fixture, []
    reply = (
        _call_end_reply(site, context) if site.category is MockCategory.CALL else None
    )
    if reply is not None:
        control -= set().union(*(context.names_under(name) for name in reply[1]))
    kept, dropped = [], []
    for spec in fixture.layout:
        if set(spec.qualified_name.upper().split(".")) & control:
            dropped.append(spec.name)
        else:
            kept.append(spec)
    if not dropped:
        return fixture, []
    todo = [
        f"*> TODO: {name} controls a loop around this call -- not set here, "
        f"or the loop never ends"
        for name in dropped
    ]
    return replace(fixture, layout=kept), todo
