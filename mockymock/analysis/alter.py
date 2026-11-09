"""ALTER under mocks (2026-11-03, NIST CCVS85 NC/SG/DB).

`ALTER P TO PROCEED TO Q` changes the target of the GO TO that paragraph P
consists of. The static analyses see that GO TO as one naming its own
target and every ALTER target of P (`extend_altered_go_tos`, applied by
`flow_targets.normalize_flow_targets` right after parsing): a multi-target
GO TO without DEPENDING ON, which never falls through and makes no count
exact -- the over-approximation every reachability walk wants.

The ALTER itself runs real. What it changed would outlive the test case
that ran it (the suite is one binary), so every case starts by ALTERing
each altered paragraph back to the target it is written with
(`alter_reset_lines`), as a fresh run of the program starts. A `GO TO.`
naming no target is a no-op until ALTERed on GnuCOBOL (control falls into
the next paragraph), so its own target is the next paragraph in source
order, or the next section when its header comes first. A paragraph that is not one plain GO TO, or a `GO TO.` with no
paragraph after it, has no state to restore: `alter_problem` refuses.
"""

from __future__ import annotations


def _procedure_paragraphs(program) -> list:
    """Every paragraph, in source order (phantom `.` artifacts left out)."""
    procedure = program.get_division("PROCEDURE") if program is not None else None
    if procedure is None:
        return []
    paragraphs = list(procedure.paragraphs)
    for section in getattr(procedure, "_sections", {}).values():
        paragraphs.extend(section.paragraphs)
    paragraphs = [p for p in paragraphs if (p.paragraph_name or "").strip(".")]
    return sorted(paragraphs, key=lambda p: p.location.line)


def _own_targets(program) -> dict[str, str]:
    """Altered paragraph -> the target its GO TO has before any ALTER: the
    one written, or for `GO TO.` the next paragraph or section (GnuCOBOL
    falls through an unaltered one)."""
    changes = alterations(program)
    ordered = _procedure_paragraphs(program)
    result: dict[str, str] = {}
    for paragraph in ordered:
        name = paragraph.paragraph_name.upper()
        go = _altered_go(paragraph) if name in changes else None
        if go is None:
            continue
        recorded = getattr(go, "mockymock_own_target", None)
        if recorded is not None:
            # `extend_altered_go_tos` ran: `GO TO.` has targets now.
            result[name] = recorded
            continue
        written = _original_target(go)
        if written is not None:
            result[name] = written
        elif not go.target_paragraphs:
            following = _next_procedure_name(program, paragraph)
            if following is not None:
                result[name] = following
    return result


def _next_procedure_name(program, paragraph) -> str | None:
    """The procedure an unaltered `GO TO.` in *paragraph* falls into: the
    next paragraph, or a section header coming first (its opening sentences
    run before its first named paragraph, #448)."""
    line = paragraph.location.line
    procedure = program.get_division("PROCEDURE")
    candidates: list[tuple[int, str]] = [
        (p.location.line, p.paragraph_name.upper())
        for p in _procedure_paragraphs(program)
        if p.location.line > line
    ]
    for section in getattr(procedure, "_sections", {}).values():
        name = str(getattr(section, "section_name", "") or "").strip(".")
        location = getattr(section, "location", None)
        if name and location is not None and location.line > line:
            candidates.append((location.line, name.upper()))
    return min(candidates)[1] if candidates else None


def alterations(program) -> dict[str, list[str]]:
    """Altered paragraph -> every target an ALTER gives it, uppercased, in
    source order."""
    result: dict[str, list[str]] = {}
    if program is None:
        return result
    for statement in program.find_all_by_type("AlterStatement"):
        for pair in getattr(statement, "alterations", None) or []:
            source = str(pair.get("from_paragraph") or "").upper()
            target = str(pair.get("to_paragraph") or "").upper()
            if source and target and target not in result.setdefault(source, []):
                result[source].append(target)
    return result


def _altered_go(paragraph):
    """The paragraph's GO TO, when the paragraph is one GO TO statement."""
    statements = [
        s for s in paragraph.statements if type(s).__name__ != "ExitStatement"
    ]
    if len(statements) != 1 or type(statements[0]).__name__ != "GoStatement":
        return None
    return statements[0]


def alter_problem(program) -> str | None:
    """Why the program's ALTERs cannot run under mocks, or None."""
    changes = alterations(program)
    if not changes:
        return None
    paragraphs = {p.paragraph_name.upper(): p for p in _procedure_paragraphs(program)}
    own = _own_targets(program)
    for name in changes:
        paragraph = paragraphs.get(name)
        if paragraph is None:
            return f"an ALTER names '{name}', which is no paragraph of the program"
        go = _altered_go(paragraph)
        original = own.get(name)
        if go is None or getattr(go, "depending_on_variable", None):
            return (
                f"paragraph '{name}' (line {paragraph.location.line}), which an "
                f"ALTER changes, is not one plain GO TO statement"
            )
        if original is None:
            return (
                f"paragraph '{name}' (line {paragraph.location.line}), which an "
                f"ALTER changes, is a GO TO with no target and no paragraph "
                f"after it, so a test case cannot start it unaltered as a run "
                f"of the program does"
            )
    return None


def _original_target(go) -> str | None:
    target = getattr(go, "target_paragraph", None)
    if isinstance(target, str) and target:
        return target.upper()
    return None


def extend_altered_go_tos(program) -> None:
    """Give an altered paragraph's GO TO its own target and every ALTER
    target, in place (after `normalize_flow_targets` upper-cases them)."""
    changes = alterations(program)
    if not changes:
        return
    own = _own_targets(program)
    for paragraph in _procedure_paragraphs(program):
        name = paragraph.paragraph_name.upper()
        go = _altered_go(paragraph) if name in changes else None
        if go is None:
            continue
        targets = [
            t.upper() for t in (go.target_paragraphs or []) if isinstance(t, str)
        ]
        if name in own:
            go.mockymock_own_target = own[name]
            if not targets:
                targets = [own[name]]
        go.target_paragraphs = targets + [t for t in changes[name] if t not in targets]


def alter_reset_lines(program) -> list[str]:
    """`ALTER P TO PROCEED TO <its own target>` for every altered paragraph:
    each test case starts with the program's GO TOs as written."""
    return [
        f"ALTER {name} TO PROCEED TO {target}"
        for name, target in _own_targets(program).items()
    ]
