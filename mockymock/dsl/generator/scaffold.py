"""Top-level `.cut` assembly: `scaffold_cut`, the bundle-less per-paragraph
scaffold and the bundle-driven per-scenario scaffold."""

from __future__ import annotations

import re
import sys
from collections.abc import Collection

from mockymock.analysis.mock_surface import BoundarySite, MockSurface, _all_paragraphs
from mockymock.dsl.fixture_bundle import FixtureBundle, Scenario
from mockymock.dsl.generator._context import (
    CallCountOverride,
    ProgramContext,
    _comment_text,
)
from mockymock.dsl.generator.bundle import _bundle_mock_directives
from mockymock.dsl.generator.counts import (
    _AFTER_STOP_REASON,
    _CONDITIONAL_SITE_REASON,
    _EARLY_EXIT_READ_REASON,
    _NO_END_READ_REASON,
    _UNREACHED_SITE_REASON,
    _USE_PROCEDURE_REASON,
    _after_possible_stop,
    _conditional_call_count_keys,
    _count_keys,
    _early_exit_read_keys,
    _endless_read_keys,
    _merged_call_counts,
    _once_per_site_counts,
    _render_expectation,
    _rendered_call_count_refs,
    _site_in_scope,
    _site_under_branch,
    _sites_for_key,
    _unlooped_read_counts,
)
from mockymock.dsl.generator.directives import _directive_for
from mockymock.dsl.generator.keys import (
    _bundle_boundary_keys,
    _known_unmockable_keys,
    _mockymock_boundary_keys,
    _program_supplied_call_keys,
    _warn_on_key_mismatch,
)
from mockymock.dsl.generator.normalize import (
    _with_accept_keys,
    _with_open_modes,
    _with_read_forms,
    _with_site_call_counts,
    _with_site_lines,
)
from mockymock.dsl.generator.rows import _row_move_lines
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry


def _capture_stub_lines(targets: list[str]) -> list[str]:
    """One `*> STUB EXPECT` comment per scaffolded capture, so the value a
    capture makes visible does not sit in the file with nothing pointing at
    it. `mockymock run --record-expectations` promotes these to real
    `EXPECT` lines from an actual run, which is exactly the workflow that
    makes a captured argument useful without the author having to guess the
    value up front."""
    return [
        f"*> STUB EXPECT {target} -- the value the program actually passed to this CALL"
        for target in targets
    ]


def _capture_targets(lines: list[str]) -> list[str]:
    """The targets of the `CAPTURE ARG` lines in an already-built mock body,
    in order. Read back off the emitted text rather than recomputed, so the
    stub comments can never name a capture the body did not actually
    declare."""
    targets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("CAPTURE ARG "):
            targets.append(stripped.rsplit(" ", 1)[-1])
    return targets


def _verification_comment_lines(scenario: Scenario) -> list[str]:
    """A `*>` note when cobol-parser could not verify that this scenario's
    own generated data actually reaches the branch it is named for.

    A scenario name is a claim; before the bundle carried a verdict, the
    only way to check it was to run the case under `--trace`. Surfacing an
    `unverified` verdict here means a reader of the generated `.cut` sees
    the caveat next to the TESTCASE it applies to, instead of trusting a
    label. Nothing is emitted for a verified scenario -- a note on every
    case would be noise, and would train people to skip these.
    """
    verification = scenario.verification or {}
    if verification.get("status") != "unverified":
        return []
    reasons = [
        f"{entry.get('field')}: {entry.get('detail')}"
        for entry in verification.get("fields") or []
        if entry.get("status") != "satisfied"
    ] + list(verification.get("gaps") or [])
    lines = [
        "*> UNVERIFIED: this scenario's generated data was not confirmed to "
        "reach the branch it is named for:"
    ]
    lines.extend(f"*>   - {reason}" for reason in reasons)
    return lines


def _case_identity(case_lines: list[str]) -> tuple[str, ...]:
    """A TESTCASE's body without its comments: two cases with the same one
    mock the same boundaries the same way, PERFORM the same paragraph and
    check the same things, so they run the same code and can only report
    the same result, whatever their names claim."""
    return tuple(
        line.strip()
        for line in case_lines
        if line.strip() and not line.strip().startswith("*>")
    )


def _duplicate_scenarios_note(count: int, entries: list[str]) -> str:
    """Why `count` scenarios got no TESTCASE of their own (NIST CCVS85,
    2026-11-02: 72 of 112 green suites ran one case up to 83 times).

    cobol-parser plans its scenarios (branch arms, failing boundaries,
    boundary values) over the program's whole main-line run, which can
    carry on past the entry paragraph: falling through into the next
    paragraphs, or `GO TO` onward (NIST's `OPEN-FILES ... GO TO
    CCVS1-EXIT`). A case PERFORMs the entry paragraph alone and returns at
    its end, so a scenario whose branch or boundary lies beyond it keeps
    none of what makes it different, and its case comes out identical to
    an earlier one under a name claiming a path it never takes."""
    shown = ", ".join(entries) or "the entry paragraph"
    return (
        f"{count} scenario(s) left out: each one's test case came out "
        f"identical to an earlier case (same mocks, same PERFORM {shown}, "
        f"same checks), so it could only repeat that case's result. A common "
        f"cause: what the scenario targets lies beyond {shown} -- the "
        f"program's main line runs on past it (falling through or GO TO), "
        f"but a test case PERFORMs {shown} alone and returns at its end"
    )


def _quote_safe(name: str) -> str:
    """The .cut grammar cannot represent a double quote inside a quoted
    name (`"[^"]*"` -- no escape syntax), so a name containing one would
    make the emitted scaffold unparseable. Substitute single quotes."""
    return name.replace('"', "'")


def scaffold_cut(
    suite_name: str,
    surface: MockSurface,
    bundle: FixtureBundle | None = None,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
) -> str:
    """Generate a starter .cut file. Without a bundle: one TESTCASE per
    paragraph with placeholder mock bodies (today's original behavior).
    With a bundle: one TESTCASE per scenario, mock bodies built from the
    bundle's own generated fixture data. See the module docstring.

    `placeholder_keys` (`mockymock generate --placeholder CATEGORY:KEY`,
    bundle-side string category paired with the fixture's own key,
    e.g. `("READ", "ORDER-FILE")`) only has an effect with a bundle --
    without one, every site already gets a placeholder body, so there is
    nothing left to downgrade. See `_bundle_directive_for`.

    `source` (the normalized program text plus its statement-start lines)
    lets a generated `MOCK READ` lift the program's own `AT END` imperative
    verbatim into its exhaustion branch instead of emitting a TODO comment
    -- see `_lifted_at_end_lines`. Optional: without it the scaffold falls
    back to the AST-driven replication and then to that TODO."""
    if bundle is None:
        return _scaffold_placeholder(suite_name, surface, source)
    return _scaffold_with_bundle(suite_name, surface, bundle, placeholder_keys, source)


# --- placeholder scaffold (no bundle) ----------------------------------------


def _scaffold_placeholder(
    suite_name: str, surface: MockSurface, context: ProgramContext | None = None
) -> str:
    sites_by_paragraph: dict[str, list[BoundarySite]] = {}
    unnamed: list[BoundarySite] = []
    for site in surface.boundary_sites:
        if site.category is None or (site.nested and site.span is None):
            continue
        if not site.paragraph_name:
            # A statement between `PROCEDURE DIVISION.` and the first
            # paragraph header belongs to no paragraph (cobolparser names
            # the holder ""), and a test case can only enter the program
            # through `PERFORM <paragraph>`. Scaffolding it emitted a bare
            # `PERFORM ` line, which the .cut parser rejects -- taking
            # every other generated test case in the file down with it.
            unnamed.append(site)
            continue
        sites_by_paragraph.setdefault(site.paragraph_name, []).append(site)

    # A paragraph name defined in two SECTIONs: `PERFORM <name>` does not
    # compile unqualified, and lint refuses any case reaching it
    # (AMBIGUOUS_PARAGRAPH, issue #284), so no case is scaffolded for it.
    ambiguous: list[str] = []
    if context is not None and context.program is not None:
        from mockymock.analysis.refusal import duplicated_paragraph_names

        duplicated = duplicated_paragraph_names(context.program)
        ambiguous = [name for name in sites_by_paragraph if name in duplicated]
        for name in ambiguous:
            del sites_by_paragraph[name]

    lines = [f'TESTSUITE "{_quote_safe(suite_name)}"', ""]
    if ambiguous:
        lines.append(
            "*> Not scaffolded: these paragraph names are defined in more "
            "than one SECTION,"
        )
        lines.append(
            "*> which mockymock cannot tell apart. Rename them to test "
            "their boundaries."
        )
        lines.extend(f"*>   {name}" for name in ambiguous)
        lines.append("")
    if unnamed:
        lines.append(
            "*> Not scaffolded: these boundaries sit before the first paragraph header,"
        )
        lines.append(
            "*> where no PERFORM can reach them. Move them into a named "
            "paragraph to test them."
        )
        lines.extend(
            f"*>   {label} at line {line}"
            for label, line in dict.fromkeys(
                (site.label, site.line) for site in unnamed
            )
        )
        lines.append("")
    for paragraph_name, own_sites in sites_by_paragraph.items():
        thru = context.thru_exit(paragraph_name) if context is not None else None
        sites = _reachable_sites(
            paragraph_name, own_sites, sites_by_paragraph, context, thru=thru
        )
        directives = _directives_for(sites, surface, context)
        if context is not None and context.whenever_quiet(
            _directive_text_lines(directives)
        ):
            # Placeholder mocks that never make a WHENEVER fire never reach
            # its handler: leave the handler's boundaries out, as lint does
            # (issue #244).
            sites = _reachable_sites(
                paragraph_name,
                own_sites,
                sites_by_paragraph,
                context,
                follow_whenever=False,
                thru=thru,
            )
            directives = _directives_for(sites, surface, context)
        labels = ", ".join(dict.fromkeys(site.label for site in sites))
        lines.append(
            f'TESTCASE "{_quote_safe(f"{paragraph_name} boundaries: {labels}")}"'
        )
        captured: list[str] = []
        for directive_line, body in directives:
            lines.append(f"    {directive_line}")
            lines.extend(f"        {body_line}" for body_line in body)
            lines.append("    END-MOCK")
            captured.extend(_capture_targets(body))
        if context is not None:
            lines.extend(f"    {line}" for line in context.setup_lines)
        perform = f"PERFORM {paragraph_name}" + (f" THRU {thru}" if thru else "")
        lines.append(f"    {perform}")
        lines.extend(f"    {line}" for line in _capture_stub_lines(captured))
        lines.append("")
    return "\n".join(lines)


def _reachable_sites(
    entry: str,
    own_sites: list[BoundarySite],
    sites_by_paragraph: dict[str, list[BoundarySite]],
    context: ProgramContext | None,
    follow_whenever: bool = True,
    thru: str | None = None,
) -> list[BoundarySite]:
    """Every boundary site a `PERFORM entry` can reach: the paragraph's own
    sites first, then those of every paragraph it reaches (PERFORM, GO TO,
    fall-through), in source order. A scaffold that mocked only the entry
    paragraph's own sites failed the very lint it has to pass whenever the
    paragraph PERFORMs another that touches a boundary (UNMOCKED_*; the
    enterprise corpus's DB2SP, whose 0000-MAIN PERFORMs the paragraph that
    opens its result-set cursor). Falls back to the own sites when
    reachability can't be established, as the bundle-driven scaffold does
    (issue #143)."""
    reachable = (
        context.reachable_from(entry, follow_whenever=follow_whenever, thru=thru)
        if context is not None
        else None
    )
    if reachable is None:
        return own_sites
    sites = list(own_sites)
    for paragraph_name, paragraph_sites in sites_by_paragraph.items():
        if paragraph_name != entry and paragraph_name in reachable:
            sites.extend(paragraph_sites)
    return sites


def _directive_text_lines(directives: list[tuple[str, list[str]]]) -> list[str]:
    """`_directives_for`'s output as the .cut lines it is written as."""
    lines: list[str] = []
    for directive_line, body in directives:
        lines.append(directive_line)
        lines.extend(f"    {body_line}" for body_line in body)
        lines.append("END-MOCK")
    return lines


def _directives_for(
    sites: list[BoundarySite],
    surface: MockSurface,
    context: ProgramContext | None = None,
) -> list[tuple[str, list[str]]]:
    directives: list[tuple[str, list[str]]] = []
    seen: set[tuple[MockCategory | None, str]] = set()
    for site in sites:
        directive = _directive_for(site, surface, context)
        if directive is None:
            continue
        key_id = (site.category, directive[0])
        if key_id in seen:
            continue
        seen.add(key_id)
        directives.append(directive)
    return directives


def _first_paragraph(program) -> str | None:
    """The first named PROCEDURE DIVISION section or paragraph, by source
    line -- where the program itself enters.

    The fallback entry for a scenario cobol-parser left without one: an IMS
    program opening with `ENTRY 'DLITCBL' USING ...` comes back with
    `entry=''` because the ENTRY statement sits in an unnamed leading
    paragraph (issue #150). A section-structured program (`A000-MAIN
    SECTION.` with its main line directly under the header) comes back the
    same way; its first *paragraph* name belongs to a later section, so
    the section headers count too (issue #238)."""
    procedure = program.get_division("PROCEDURE") if program is not None else None
    if procedure is None:
        return None

    def line_of(node) -> int:
        return int(getattr(getattr(node, "location", None), "line", 0) or 0)

    named = [
        (line_of(paragraph), str(paragraph.paragraph_name))
        for paragraph in _all_paragraphs(procedure)
        if getattr(paragraph, "paragraph_name", "")
    ]
    named.extend(
        (line_of(section), str(section.section_name))
        for section in getattr(procedure, "_sections", {}).values()
        if getattr(section, "section_name", "")
    )
    from mockymock.analysis.declaratives import declarative_paragraphs

    # DECLARATIVES open the PROCEDURE DIVISION, but the program enters
    # after END DECLARATIVES.
    in_declaratives = declarative_paragraphs(program)
    named = [pair for pair in named if pair[1] not in in_declaratives]
    if not named:
        return None
    return min(named, key=lambda pair: pair[0])[1]


def _build_shadow_tally_registry(
    bundle: FixtureBundle,
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    fallback_entry: str | None = None,
) -> TallyRegistry:
    """A `TallyRegistry` built over every (category, key) that will
    actually get a MOCK directive in the generated file, in the same
    first-appearance order the real, fully-parsed suite will eventually
    present them in -- so a hand-rolled tally-branching mock body (see
    `_read_body`) can reference the *exact* `UT-...-TALLY` field name the
    real splice pipeline will independently compute, without this
    generator needing its own parsed `MockTestSuite` to run a real
    registry over (the .cut text doesn't exist yet -- this IS how it gets
    built)."""
    case = MockTestCase(name="_shadow", perform_target="_SHADOW")
    seen: set[tuple[MockCategory, str]] = set()
    for scenario in bundle.scenarios:
        if not (scenario.entry or fallback_entry):
            continue
        for fixture in scenario.fixtures:
            try:
                category = MockCategory(fixture.category)
            except ValueError:
                continue
            pair = (category, fixture.key)
            if pair in mockymock_keys and pair not in seen:
                seen.add(pair)
                case.mocks.append(MockDirective(category, fixture.key))
    # Then the placeholder-mocked keys, in the order their directives are
    # written: a looped DL/I get-next placeholder body needs its tally too.
    for pair in mockymock_keys:
        if pair not in seen:
            seen.add(pair)
            case.mocks.append(MockDirective(*pair))
    suite = MockTestSuite(name="_shadow", test_cases=[case])
    return TallyRegistry(suite)


def _entry_parameter_lines(
    scenario: Scenario, source: ProgramContext | None
) -> list[str]:
    """`MOVE`s of the values a caller passes through the program's own
    PROCEDURE DIVISION USING items (issue #275), before the PERFORM: for a
    called subprogram they are its whole input."""
    parameters = scenario.entry_parameters
    if parameters is None or not parameters.sequence:
        return []
    moves = _row_move_lines(
        parameters.sequence[0], parameters, source, in_mock_body=False
    )
    if not moves:
        return []
    return [f"*> what the caller of {parameters.key} passes (USING)", *moves]


_MOCK_CALL_LINE = re.compile(r'^\s*MOCK\s+CALL\s+("?)([^"\s]+)\1', re.IGNORECASE)


def _cancel_cover_lines(
    surface: MockSurface,
    reachable: Collection[str] | None,
    directive_lines: list[str],
) -> list[str]:
    """An empty `MOCK CALL` for every program a reachable CANCEL names that
    the case does not mock already (NIST IC203A: `CANCEL ID1, "IC205A",
    ID2`, with ID2 never CALLed). The refusal gate accepts a CANCEL only
    when the case mocks a CALL for each name it carries: with every CALL
    mocked no real module is ever loaded, so the CANCEL is a no-op. A
    literal name gets `MOCK CALL "X"`, a data name `MOCK CALL X` (the
    dynamic form, keyed by the identifier)."""
    mocked: set[tuple[bool, str]] = set()
    for line in directive_lines:
        match = _MOCK_CALL_LINE.match(line)
        if match:
            mocked.add((bool(match.group(1)), match.group(2).upper()))
    lines: list[str] = []
    for site in surface.boundary_sites:
        if site.label != "CANCEL" or site.category is not None:
            continue
        if reachable is not None and site.paragraph_name not in reachable:
            continue
        statement = site.statement
        names = list(getattr(statement, "program_names", ()) or ())
        literal = list(getattr(statement, "program_names_literal", ()) or ())
        for index, name in enumerate(names):
            is_literal = index < len(literal) and literal[index]
            if not name or (is_literal and '"' in name):
                continue
            pair = (is_literal, name.upper())
            if pair in mocked:
                continue
            mocked.add(pair)
            shown = f'"{name}"' if is_literal else name
            lines.extend(
                [
                    f"*> CANCEL {shown} (line {site.line}): never CALLed here; "
                    f"this mock keeps the CANCEL a no-op",
                    f"MOCK CALL {shown}",
                    "END-MOCK",
                ]
            )
    return lines


def _scaffold_with_bundle(
    suite_name: str,
    surface: MockSurface,
    bundle: FixtureBundle,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
) -> str:
    bundle = _with_accept_keys(
        _with_site_call_counts(
            _with_open_modes(
                _with_read_forms(_with_site_lines(bundle, surface), surface),
                surface,
            ),
            surface,
        )
    )
    mockymock_keys = _mockymock_boundary_keys(surface)
    _warn_on_key_mismatch(
        mockymock_keys,
        _bundle_boundary_keys(bundle),
        _known_unmockable_keys(surface),
        _program_supplied_call_keys(source.program if source is not None else None),
    )
    fallback_entry = _first_paragraph(source.program) if source is not None else None
    registry = _build_shadow_tally_registry(bundle, mockymock_keys, fallback_entry)

    lines = [f'TESTSUITE "{_quote_safe(suite_name)}"', ""]
    # What the bundle itself says it could not generate (issue #331): the
    # bundle-level entries under TESTSUITE, each fixture's own above its
    # MOCK (`_bundle_mock_directives`), and all of them on stderr -- a
    # header/detail FD generated through its first 01 record only must
    # not read as a clean scaffold whose recorded goldens can be trusted.
    fixture_notes = [
        note
        for scenario in bundle.scenarios
        for fixture in scenario.fixtures
        for note in fixture.unresolved
    ]
    suite_notes = [
        n for n in dict.fromkeys(bundle.unresolved) if n not in fixture_notes
    ]
    if suite_notes:
        lines.extend(f"*> NOTE: {_comment_text(note)}" for note in suite_notes)
        lines.append("")
    for note in dict.fromkeys([*bundle.unresolved, *fixture_notes]):
        print(
            f"mockymock generate: note: the fixture bundle could not generate "
            f"everything -- {note}",
            file=sys.stderr,
        )
    skipped_scenarios = 0
    duplicate_scenarios: list[str] = []
    emitted_bodies: set[tuple[str, ...]] = set()
    for scenario in bundle.scenarios:
        entry = scenario.entry or fallback_entry
        if not entry:
            # Nothing to PERFORM -- can't scaffold a TESTCASE for this
            # scenario at all. Should not happen for a real program with a
            # non-empty PROCEDURE DIVISION; reported below, not per-scenario.
            skipped_scenarios += 1
            continue
        # Only the sites this case can reach: a mock for a boundary in a
        # paragraph nothing PERFORMs from the entry (or reached only via a
        # CICS HANDLE) is UNMATCHED_MOCK to the very lint this file has to
        # pass (issue #143). Its VERIFY goes with it -- `_render_expectation`
        # drops counts for keys that got no MOCK directive.
        thru = source.main_line_thru(entry) if source is not None else None
        reachable = (
            source.reachable_from(entry, thru=thru) if source is not None else None
        )
        case_start = len(lines)
        lines.append(f'TESTCASE "{_quote_safe(scenario.name)}"')
        lines.extend(f"    {line}" for line in _verification_comment_lines(scenario))
        scenario_keys = (
            mockymock_keys
            if reachable is None
            else {
                pair: site
                for pair, site in mockymock_keys.items()
                if site.paragraph_name in reachable
            }
        )
        directive_lines, declared_keys, call_count_overrides = _bundle_mock_directives(
            scenario, surface, scenario_keys, registry, placeholder_keys, source
        )
        if (
            source is not None
            and reachable is not None
            and source.whenever_quiet(directive_lines)
        ):
            # Mocks that never make a WHENEVER fire never reach its handler
            # either: lint then leaves the handler out of the reachable set
            # and would refuse its boundaries' mocks as UNMATCHED (#244).
            quiet = source.reachable_from(entry, follow_whenever=False, thru=thru)
            if quiet is not None and quiet != reachable:
                reachable = quiet
                scenario_keys = {
                    pair: site
                    for pair, site in mockymock_keys.items()
                    if site.paragraph_name in reachable
                }
                directive_lines, declared_keys, call_count_overrides = (
                    _bundle_mock_directives(
                        scenario,
                        surface,
                        scenario_keys,
                        registry,
                        placeholder_keys,
                        source,
                    )
                )
        lines.extend(f"    {line}" for line in directive_lines)
        lines.extend(
            f"    {line}"
            for line in _cancel_cover_lines(surface, reachable, directive_lines)
        )
        if source is not None:
            lines.extend(f"    {line}" for line in source.setup_lines)
        lines.extend(f"    {line}" for line in _entry_parameter_lines(scenario, source))
        lines.append(f"    PERFORM {entry}" + (f" THRU {thru}" if thru else ""))
        lines.extend(
            f"    {line}"
            for line in _capture_stub_lines(_capture_targets(directive_lines))
        )
        expectations = _merged_call_counts(scenario.expectations)
        scope = row_scope = None
        if source is not None and reachable is not None:
            scope = source.exact_count_scope(entry, reachable)
            row_scope = source.exact_count_scope(entry, reachable, loops_exact=True)
        for key_pair, reason in _conditional_call_count_keys(
            expectations, surface, reachable, scope, row_scope
        ):
            # Wins over a loop-end count (a browse's READNEXT answered once
            # with a row and once with ENDFILE): that count holds only when
            # the case reaches the loop, which here is not known.
            existing = call_count_overrides.get(key_pair)
            if existing is None or (
                existing.demote_reason is None
                and reason in (_CONDITIONAL_SITE_REASON, _UNREACHED_SITE_REASON)
                and source is not None
                and any(
                    _site_under_branch(site, source.program)
                    # After a branch that may end the run (`IF ... GOBACK`):
                    # the scenario taking it never reaches the loop at all.
                    or (row_scope is not None and not _site_in_scope(site, row_scope))
                    for site in _sites_for_key(
                        *key_pair,
                        surface,
                        reachable,
                        _count_keys(expectations).get(key_pair[0], ()),
                    )
                )
            ):
                if row_scope is not None and any(
                    _after_possible_stop(site, row_scope)
                    for site in _sites_for_key(
                        *key_pair,
                        surface,
                        reachable,
                        _count_keys(expectations).get(key_pair[0], ()),
                    )
                ):
                    reason = _AFTER_STOP_REASON
                call_count_overrides[key_pair] = CallCountOverride(
                    demote_reason=reason, from_placeholder=False
                )
        if source is not None:
            for key_pair in _endless_read_keys(
                expectations, surface, reachable, source
            ):
                call_count_overrides.setdefault(
                    key_pair,
                    CallCountOverride(
                        demote_reason=_NO_END_READ_REASON, from_placeholder=False
                    ),
                )
            for key_pair in _early_exit_read_keys(
                expectations, surface, reachable, source
            ):
                # Wins over an end-of-file count (`_status_read_eof`): a
                # row that takes the exit stops the reads before it. A
                # placeholder READ ends on its first call, before any row.
                existing = call_count_overrides.get(key_pair)
                if existing is None or (
                    existing.demote_reason is None and not existing.from_placeholder
                ):
                    call_count_overrides[key_pair] = CallCountOverride(
                        demote_reason=_EARLY_EXIT_READ_REASON,
                        from_placeholder=False,
                    )
            for key_pair, count in _unlooped_read_counts(
                expectations, surface, reachable, source
            ).items():
                call_count_overrides.setdefault(
                    key_pair, CallCountOverride(count=count, from_placeholder=False)
                )
        if scope is not None:
            for key_pair, count in _once_per_site_counts(
                expectations, surface, reachable, scope
            ).items():
                call_count_overrides.setdefault(
                    key_pair, CallCountOverride(count=count, from_placeholder=False)
                )
        if surface.use_procedures is not None:
            # A mocked file statement's exception outcome runs a USE
            # procedure, which can end a read loop early or change what
            # runs next (NIST SQ122A): no count is exact.
            for expectation in expectations:
                if expectation.kind != "call_count":
                    continue
                category_str, _, key = expectation.ref.partition(":")
                try:
                    key_pair = (MockCategory(category_str), key)
                except ValueError:
                    continue
                call_count_overrides[key_pair] = CallCountOverride(
                    demote_reason=_USE_PROCEDURE_REASON, from_placeholder=False
                )
        counted_boundaries = _rendered_call_count_refs(
            expectations, declared_keys, call_count_overrides
        )
        # One check per line: a record written by 80 WRITE sites (a NIST
        # main line) gave 80 identical `*> STUB EXPECT` lines.
        rendered: set[str] = set()
        for expectation in expectations:
            for line in _render_expectation(
                expectation,
                declared_keys,
                call_count_overrides,
                counted_boundaries,
                source.pictures if source is not None else None,
                source,
            ):
                if line.strip() and line in rendered:
                    continue
                rendered.add(line)
                lines.append(f"    {line}")
        body = _case_identity(lines[case_start + 1 :])
        if body in emitted_bodies:
            del lines[case_start:]
            duplicate_scenarios.append(scenario.name)
            continue
        emitted_bodies.add(body)
        lines.append("")

    if duplicate_scenarios:
        entries = sorted(
            {scenario.entry or fallback_entry or "" for scenario in bundle.scenarios}
            - {""}
        )
        note = _duplicate_scenarios_note(len(duplicate_scenarios), entries)
        lines[2:2] = [f"*> NOTE: {note}", ""]
        print(f"mockymock generate: note: {note}", file=sys.stderr)
    if skipped_scenarios:
        print(
            f"mockymock generate --with-data: WARNING: {skipped_scenarios} "
            f"scenario(s) had no entry paragraph and could not be scaffolded "
            f"as a TESTCASE",
            file=sys.stderr,
        )
    return "\n".join(lines)
