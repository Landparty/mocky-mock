"""Auto-scaffolds a starter .cut file from a MockSurface.

One TESTCASE per paragraph that has at least one mockable boundary site;
the TESTCASE mocks ALL of that paragraph's mockable sites (deduped by
key) -- a scaffold that mocked only some of them would walk users
straight into the refusal gate's UNMOCKED_* checks (an unmocked CALL has
nowhere to link, unmocked file I/O would hit a nonexistent sandbox file,
unmocked EXEC cannot compile, unmocked console ACCEPT reads stdin).

Nested sites count as mockable only when `annotate_nested_sites` gave
them a validated splice span; unspliceable nested sites are skipped here
and reported by the CLI's unsupported-boundaries listing instead.

Placeholder bodies are minimal-but-runnable (MOVE 0 TO RETURN-CODE for
calls, MOVE 0 TO SQLCODE for SQL, empty for file ops) and are expected to
be replaced with real mock behavior. MQ API calls are emitted with the
`MOCK MQ` sugar so the .cut reads at the right level of intent.

The scaffold only covers each paragraph's OWN sites: boundaries reached
transitively through PERFORM still need their MOCK directives added by
hand (the run command's refusal gate names them precisely).
"""

from __future__ import annotations

from mockymock.analysis.mock_surface import BoundarySite, MockSurface
from mockymock.dsl.model import FILE_OP_CATEGORIES, MockCategory

_PLACEHOLDER_BODIES: dict[MockCategory, list[str]] = {
    MockCategory.CALL: ["MOVE 0 TO RETURN-CODE"],
    MockCategory.SQL: ["MOVE 0 TO SQLCODE"],
}


def scaffold_cut(suite_name: str, surface: MockSurface) -> str:
    """Generate a starter .cut file from every mockable boundary site."""
    sites_by_paragraph: dict[str, list[BoundarySite]] = {}
    for site in surface.boundary_sites:
        if site.category is None or (site.nested and site.span is None):
            continue
        sites_by_paragraph.setdefault(site.paragraph_name, []).append(site)

    lines = [f'TESTSUITE "{suite_name}"', ""]
    for paragraph_name, sites in sites_by_paragraph.items():
        directives = _directives_for(sites, surface)
        labels = ", ".join(dict.fromkeys(site.label for site in sites))
        lines.append(f'TESTCASE "{paragraph_name} boundaries: {labels}"')
        for directive_line, body in directives:
            lines.append(f"    {directive_line}")
            lines.extend(f"        {body_line}" for body_line in body)
            lines.append("    END-MOCK")
        lines.append(f"    PERFORM {paragraph_name}")
        lines.append("")
    return "\n".join(lines)


def _directives_for(
    sites: list[BoundarySite], surface: MockSurface
) -> list[tuple[str, list[str]]]:
    directives: list[tuple[str, list[str]]] = []
    seen: set[tuple[MockCategory, str]] = set()
    for site in sites:
        directive = _directive_for(site, surface)
        if directive is None:
            continue
        key_id = (site.category, directive[0])
        if key_id in seen:
            continue
        seen.add(key_id)
        directives.append(directive)
    return directives


def _directive_for(
    site: BoundarySite, surface: MockSurface
) -> tuple[str, list[str]] | None:
    category = site.category
    body = list(_PLACEHOLDER_BODIES.get(category, []))

    if category is MockCategory.CALL:
        name = site.keys[0] if site.keys else ""
        keyword = "MQ" if site.is_mq else "CALL"
        return f'MOCK {keyword} "{name}"', body

    if category in FILE_OP_CATEGORIES:
        if not site.keys:
            return None  # no usable key parsed; run's refusal gate will name it
        return f"MOCK {category.value} {site.keys[0]}", body

    if category is MockCategory.ACCEPT:
        if not site.keys:
            return None
        target = site.keys[0]
        return f"MOCK ACCEPT {target}", [f"MOVE SPACES TO {target}"]

    # SQL / CICS / DLI: shortest word-prefix of this site's normalized text
    # that is unique among the program's sites of the same category, so the
    # scaffold never generates an AMBIGUOUS_MOCK pair.
    prefix = _unique_prefix(site, surface)
    return f'MOCK {category.value} "{prefix}"', body


def _unique_prefix(site: BoundarySite, surface: MockSurface) -> str:
    words = (site.match_text or "").split()
    if not words:
        return ""
    others = [
        other.match_text or ""
        for other in surface.boundary_sites
        if other.category is site.category and other is not site
    ]
    for length in range(1, len(words) + 1):
        prefix = " ".join(words[:length])
        collisions = [o for o in others if o.startswith(prefix)]
        if not collisions:
            return prefix
    return " ".join(words)
