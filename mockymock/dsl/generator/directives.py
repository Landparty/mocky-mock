"""Bundle-less (placeholder) MOCK directive rendering, including the public
`directive_snippet` renderer refusals and `--fill` reuse."""

from __future__ import annotations

from mockymock.analysis.mock_surface import BoundarySite, MockSurface
from mockymock.dsl.generator._context import _PLACEHOLDER_BODIES, ProgramContext
from mockymock.dsl.generator.cics import _accept_loop_end_lines, _cics_loop_end_lines
from mockymock.dsl.generator.files import _end_of_file_placeholder
from mockymock.dsl.generator.ims import (
    _call_loop_end_lines,
    _dli_loop_end_lines,
    _dli_success_reply,
)
from mockymock.dsl.generator.keys import _unique_prefix, file_op_key
from mockymock.dsl.generator.mq import _mq_success_reply
from mockymock.dsl.model import (
    FILE_OP_CATEGORIES,
    REPORT_WRITER_CATEGORIES,
    MockCategory,
)


def directive_snippet(
    site: BoundarySite,
    surface: MockSurface,
    file_status_fields: dict[str, str] | None = None,
) -> str | None:
    """Render the exact `.cut` text a bundle-less scaffold would emit for
    this one boundary site: a `MOCK ... END-MOCK` block, 4-space-indented
    header/footer and 8-space-indented body, matching
    `_scaffold_placeholder`'s own rendering exactly. `None` for a site
    `_directive_for` itself declines to render (category=None, an
    unrepresentable key/prefix, an unparsed CALL literal, ...) -- those
    have no mechanical fix to suggest.

    This is the one place both the refusal gate
    (`RefusalReason.suggested_fix`, see docs/2026-09-15-actionable-
    refusals-and-fill-design.md) and `generate --fill` get their fix
    text from -- neither re-renders a directive independently, so the
    two can never drift apart, and a scaffold produced by plain
    `generate` always matches what a refusal message would have
    suggested for the same site. That includes declining the sites the
    scaffold itself skips (a nested site with no recorded span, a
    top-level site the splicer cannot rewrite): suggesting a MOCK the
    next lint would refuse as UNSUPPORTED_NESTED_MOCK_TARGET /
    UNSPLICEABLE is not a fix.

    `file_status_fields` (`analyze_file_status_fields`) lets a READ's
    placeholder report end of file through the file's own FILE STATUS
    field -- see `_end_of_file_placeholder`."""
    if site.category is None:
        return None
    if site.nested and site.span is None:
        return None
    if not site.nested and site.unspliceable_reason:
        return None
    rendered = _directive_for(site, surface, file_status_fields=file_status_fields)
    if rendered is None:
        return None
    header, body = rendered
    lines = [f"    {header}"]
    lines.extend(f"        {body_line}" for body_line in body)
    lines.append("    END-MOCK")
    return "\n".join(lines)


def _with_captures(
    category: MockCategory,
    key: str,
    body: list[str],
    context: ProgramContext | None,
) -> list[str]:
    """Prepend this boundary's scaffolded `CAPTURE ARG` lines to a mock
    body. First, deliberately: `injector.build_site_dispatch` emits the
    capture MOVEs before the body's own statements so a capture always
    reflects what the real caller passed, and keeping the `.cut` in the
    same order means the file reads the way it executes."""
    if context is None:
        return body
    return context.captures_for(category, key) + body


#: Above this many known targets a per-target EVALUATE repeats the body
#: too often to help; the targets are listed in a comment instead.
_MAX_TARGET_BRANCHES = 5


def _per_target_body(
    key: str, body: list[str], context: ProgramContext | None
) -> list[str]:
    """A dynamic CALL's mock body, given the program names its identifier
    is known to hold (`ProgramContext.dynamic_targets`): one `WHEN` per
    target, each starting from the same generated body, so a test can make
    each callee answer differently. `WHEN OTHER` keeps the body too, so a
    value the analysis did not see behaves exactly as the unbranched mock.
    A single target, too many, or an identifier the body cannot name
    unqualified gets a comment naming the targets instead."""
    if context is None:
        return body
    known = context.dynamic_targets.get(key.upper())
    if not known:
        return body
    targets, complete = known
    listed = ", ".join(f'"{target}"' for target in targets)
    more = "" if complete else ", and values this analysis cannot follow"
    comment = f"*> {key} can name {listed}{more}"
    if (
        len(targets) + (0 if complete else 1) < 2
        or len(targets) > _MAX_TARGET_BRANCHES
        or not context.is_unique_name(key)
    ):
        return [comment, *body]
    lines = [comment, f"EVALUATE {key}"]
    for target in targets:
        lines.append(f'    WHEN "{target}"')
        lines.extend(f"        {line}" for line in body or ["CONTINUE"])
    lines.append("    WHEN OTHER")
    lines.extend(f"        {line}" for line in body or ["CONTINUE"])
    lines.append("END-EVALUATE")
    return lines


def _placeholder_body_for(
    category: MockCategory, key: str, site: BoundarySite | None = None
) -> list[str]:
    """The body `_directive_for` gives `(category, key)` outside a fixture
    bundle: `_PLACEHOLDER_BODIES`'s entry (CALL/DYNCALL/SQL), or ACCEPT's
    own `INITIALIZE <key>`, or empty for everything else (the file-op
    verbs, CICS, DLI). Factored out of `_directive_for` so the
    bundle-driven scaffold's `--placeholder` downgrade (`_bundle_directive_for`)
    can reuse the exact same body a bundle-less scaffold would have
    emitted for this site, rather than a second, driftable copy of this
    per-category logic."""
    if category is MockCategory.ACCEPT:
        # INITIALIZE, not MOVE SPACES: legal for an alphanumeric, numeric
        # or numeric-edited target alike (cobc rejects MOVE SPACES to a
        # numeric item), and sets each to its category's default -- this
        # body is lint's suggested fix and `--fill`'s insert (issue #330).
        # The ACCEPT's own target, subscript/qualifier included: the key is
        # its bare data-name (issue #311).
        target = site.accept_target if site is not None else None
        if (target or key).upper() == "OMITTED":
            # `ACCEPT OMITTED` waits for a key and stores nothing: the
            # mock answers it at once (GnuCOBOL rejects INITIALIZE OMITTED).
            return []
        return [f"INITIALIZE {target or key}"]
    return list(_PLACEHOLDER_BODIES.get(category, []))


def _directive_for(
    site: BoundarySite,
    surface: MockSurface,
    context: ProgramContext | None = None,
    file_status_fields: dict[str, str] | None = None,
) -> tuple[str, list[str]] | None:
    category = site.category
    if category is None:
        # scaffold_cut filters these out already; guard for direct callers
        return None

    if category is MockCategory.CALL:
        if not site.keys:
            # a static CALL whose literal never parsed: emitting
            # `MOCK CALL ""` would be rejected at parse time (empty key),
            # so skip it like the file-op/ACCEPT branches do; run's
            # refusal gate will name the unmocked site.
            return None
        key = site.keys[0]
        if '"' in key:
            # The .cut grammar cannot represent a quote inside a quoted
            # key, and _quote_safe's substitution is no fix for a KEY --
            # the directive would silently stop matching its site. Skip
            # it like an unparsed key: run's refusal gate names the
            # unmocked site loudly (2026-08-12 audit Finding 20).
            return None
        keyword = "MQ" if site.is_mq else "CALL"
        # A bundle-less MQI placeholder answers the call's own CompCode and
        # Reason (its last two USING arguments), as the data-driven path
        # does: RETURN-CODE alone left a program's `IF WS-COMPCODE = 0`
        # test reading whatever the field held before the call.
        body = _dli_success_reply(
            _mq_success_reply(_placeholder_body_for(category, key), site), site
        ) + _call_loop_end_lines(site, context, None)
        return f'MOCK {keyword} "{key}"', _with_captures(category, key, body, context)

    if category is MockCategory.DYNCALL:
        # bare key = dynamic CALL through this identifier; quoting it would
        # turn the directive into a static-literal mock that never matches
        key = site.keys[0]
        body = _per_target_body(key, _placeholder_body_for(category, key), context)
        return f"MOCK CALL {key}", _with_captures(category, key, body, context)

    if category in FILE_OP_CATEGORIES:
        if not site.keys:
            return None  # no usable key parsed; run's refusal gate will name it
        key = file_op_key(site, surface)
        return f"MOCK {category.value} {key}", _placeholder_body_for(
            category, key
        ) + _end_of_file_placeholder(site, context, file_status_fields)

    if category is MockCategory.ACCEPT:
        if not site.keys:
            return None
        key = site.keys[0]
        end_lines = _accept_loop_end_lines(site, context, None)
        body = _placeholder_body_for(category, key, site)
        if end_lines and not end_lines[0].startswith("*>"):
            body = end_lines  # the sentinel replaces the placeholder value
        else:
            body = body + end_lines
        return f"MOCK ACCEPT {key}", body

    if category in REPORT_WRITER_CATEGORIES:
        # INITIATE/GENERATE/TERMINATE: bare report name, empty body (the
        # splice alone is the mock -- nothing flows back into the program).
        if not site.keys:
            return None
        key = site.keys[0]
        return f"MOCK {category.value} {key}", _placeholder_body_for(category, key)

    # SQL / CICS / DLI: shortest word-prefix of this site's normalized text
    # that is unique among the program's sites of the same category, so the
    # scaffold never generates an AMBIGUOUS_MOCK pair.
    prefix = _unique_prefix(site, surface)
    if '"' in prefix:
        # Same unrepresentable-quote skip as the CALL branch above: an
        # EXEC statement whose unique prefix runs into a string literal
        # containing a double quote cannot be written as a quoted key.
        return None
    body = _placeholder_body_for(category, prefix)
    if category is MockCategory.DLI:
        body = body + _dli_loop_end_lines(site, context, None)
    if category is MockCategory.CICS:
        body = body + _cics_loop_end_lines(site, context, None)
    return f'MOCK {category.value} "{prefix}"', body
