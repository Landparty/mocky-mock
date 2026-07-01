"""Auto-scaffolds a starter .cut file from a MockSurface."""

from __future__ import annotations

from mockymock.analysis.mock_surface import MockSurface


def scaffold_cut(suite_name: str, surface: MockSurface) -> str:
    """Generate a starter .cut file from static CALL sites in a mock surface.

    Args:
        suite_name: Name for the TESTSUITE directive.
        surface: MockSurface containing analyzed call sites.

    Returns:
        A string containing valid .cut syntax with one TESTCASE per static call site.
        The MOCK CALL bodies contain MOVE 0 TO RETURN-CODE as a placeholder that
        users are expected to replace with real mock return values.
    """
    lines = [f'TESTSUITE "{suite_name}"', ""]
    for site in surface.static_call_sites():
        lines.append(f'TESTCASE "Calls {site.program_name} from {site.paragraph_name}"')
        lines.append(f'    MOCK CALL "{site.program_name}"')
        lines.append("        MOVE 0 TO RETURN-CODE")
        lines.append("    END-MOCK")
        lines.append(f"    PERFORM {site.paragraph_name}")
        lines.append("")
    return "\n".join(lines)
