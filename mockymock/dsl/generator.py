"""Auto-scaffolds a starter .cut file from a MockSurface."""

from __future__ import annotations

from mockymock.analysis.mock_surface import MockSurface


def scaffold_cut(suite_name: str, surface: MockSurface) -> str:
    """Generate a starter .cut file from static CALL sites in a mock surface.

    Args:
        suite_name: Name for the TESTSUITE directive.
        surface: MockSurface containing analyzed call sites.

    Returns:
        A string containing valid .cut syntax with one TESTCASE per
        paragraph that has static call sites. When a paragraph has more
        than one static call site, its TESTCASE mocks ALL of that
        paragraph's call sites (deduped by distinct program name), not just
        one -- an unmocked reachable static CALL has nowhere to link (the
        called program's real source is never part of the compilation
        unit), so a scaffold that mocked only one call per site would walk
        users straight into refusal.py's UNMOCKED_CALL gate. The MOCK CALL
        bodies contain MOVE 0 TO RETURN-CODE as a placeholder that users are
        expected to replace with real mock return values.
    """
    call_names_by_paragraph: dict[str, list[str]] = {}
    for site in surface.static_call_sites():
        names = call_names_by_paragraph.setdefault(site.paragraph_name, [])
        if site.program_name not in names:
            names.append(site.program_name)

    lines = [f'TESTSUITE "{suite_name}"', ""]
    for paragraph_name, program_names in call_names_by_paragraph.items():
        calls_desc = ", ".join(program_names)
        lines.append(f'TESTCASE "Calls {calls_desc} from {paragraph_name}"')
        for program_name in program_names:
            lines.append(f'    MOCK CALL "{program_name}"')
            lines.append("        MOVE 0 TO RETURN-CODE")
            lines.append("    END-MOCK")
        lines.append(f"    PERFORM {paragraph_name}")
        lines.append("")
    return "\n".join(lines)
