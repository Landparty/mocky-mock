# Conditionally-Nested Intermediate PERFORM — Design

Date: 2026-07-10
Status: design approved; spikes required before implementation is trusted (see
Verification plan) — same posture as every other fact this feature depends on.

## Problem

`docs/2026-07-08-goback-stop-run-support-design.md`'s Approach B neutralizes a
`STOP RUN`/`GOBACK` terminator by propagating an early-exit flag back up the
real `PERFORM` call chain: `IF UT-EARLY-EXIT = "Y" EXIT PARAGRAPH END-IF` is
inserted immediately after every intermediate `PERFORM` on the chain. That
design already covers the terminator's own paragraph being conditionally
nested (spike #2: a terminator inside an `IF`, in its own paragraph, is
safely neutralized) and an unconditional intermediate `PERFORM` (spike #3).

What it does not cover: an intermediate *link* in the chain — the `PERFORM`
that hops from one paragraph to the next on the way to the terminator — being
itself nested inside a conditional body, e.g.:

```cobol
2000-MIDDLE.
    IF WS-SHOULD-CONTINUE = "Y"
        PERFORM 3000-INNER
    END-IF
    DISPLAY "MIDDLE DONE".
```

`mockymock/analysis/refusal.py`'s `_plain_perform_edges_from` only scans a
paragraph's `.statements` list directly — a `PerformStatement` nested inside
an `IF`/`EVALUATE`/inline-`PERFORM` body is invisible to it. The paragraph it
targets (`3000-INNER` above) never enters the BFS's `seen` set, so a
terminator reachable only through it falls through to the generic "reachable
but not via a plain chain" refusal (`UNSUPPORTED_TERMINATOR_LAYOUT`) — not a
crash, but an unnecessarily broad refusal for a shape the underlying
mechanism (`EXIT PARAGRAPH` propagation) has no inherent reason to reject.

## Design

### 1. Detection — extending the chain BFS into nested bodies

`refusal.py` gains a new recursive walker that mirrors
`mock_surface.py`'s `_walk_statements` pattern exactly (same `nested`/
`in_boundary` threading), filtering for the plain-chain-edge shape instead of
boundary statements. For each paragraph, walk `.statements` and yield every
`PerformStatement` with `thru_paragraph is None`, `target_paragraph` set, and
`perform_type == "SIMPLE"`, tagged with:

- `nested`: `False` only at depth 0 (a direct member of `paragraph.statements`
  — today's only supported shape); `True` at any depth ≥ 1 — inside an
  `IF`/`ELSE` branch, an `EVALUATE` `WHEN`/`WHEN OTHER` branch, or an inline
  `PERFORM ... END-PERFORM` loop body (via `_nested_statement_lists`'
  `then_statements`/`else_statements`/`when_clauses`/`inline_statements`,
  already covering all three).
- `in_boundary`: sticky, `True` once recursion has entered another boundary
  statement's clause body (`CallStatement`'s `on_exception`, a file
  statement's `at_end_clause`, etc. — `mock_surface._BOUNDARY_STATEMENT_TYPES`)
  — mirrors `_walk_statements`' identical `child_in_boundary` propagation.

`_plain_perform_edges_from` uses this walker in place of its current
`paragraph.statements` scan; the BFS's `seen`/`stack` traversal and
target-pushing are otherwise unchanged. Each edge in the returned list now
carries `(statement, nested)` instead of a bare statement (`in_boundary=True`
edges are dropped before the edge list is returned — see below, this is a
hard refusal, not a valid edge at all).

### 2. New validation/insertion-point function (`source_map.py`)

A new `nested_chain_perform_problem(statement, scope_map, lines) ->
tuple[tuple[int, int] | None, str | None]`, a trimmed sibling of
`_nested_site_span`: the same "does the statement own its start line" check
and "does the next scope boundary also own its own line" check, evaluated
against the **full, unfiltered** `scope_map.boundaries` (not just entries
with `top_level=True`) — this is what correctly detects a `PERFORM` sharing
its line with `END-IF`/`ELSE`/`WHEN`, which `statement_top_level_problem`'s
`b.top_level`-filtered check would silently miss. Drops
`_nested_site_span`'s EXEC-range and `_VERB_TERMINATORS` handling, neither of
which applies to a plain out-of-line `PERFORM` statement (a `SIMPLE`
out-of-line `PERFORM` has no clause body of its own, so
`_nested_statement_lists(statement)` is always empty here — the "has
conditional clause bodies of its own" guard in `_nested_site_span` can never
trigger for this statement type and is omitted).

Returns `(start, end)` on success — `end` is precisely the line
`orchestrator.py`'s `insert_lines_after` needs, computed the same way
`_nested_site_span` finds its span end (next scope-map boundary, minus one),
so the check lands immediately after the `PERFORM`, inside the same
conditional branch, before whatever closes it.

Any edge tagged `in_boundary=True` (from step 1) refuses unconditionally,
without ever calling this function — structurally identical to the existing
`nested_in_boundary` rule `_nested_site_span` already enforces for
`BoundarySite`s: splicing the enclosing `CALL`/`READ`/etc. statement would
delete the `PERFORM` and any inserted check along with it. This is not a v1
scope choice; it is a permanent incompatibility with how boundary splicing
works, and is documented as such (see Out of scope).

### 3. Wiring

`TerminatorPlan.chain_performs` changes from `list[PerformStatement]` to
`list[tuple[PerformStatement, bool]]` (statement, `nested`) — every existing
consumer that only cared about the statement itself is updated to unpack the
tuple.

**Dedup trap to watch for:** both existing dedup sites — `find_terminator_plans`'s
per-plan merge (`existing_ids = {id(p) for p in plan.chain_performs}`) and
`orchestrator.py`'s insertion loop (`seen_perform_ids`) — key off `id(perform)`
directly today. Once `chain_performs` holds tuples, `id(perform)` would key
off the *tuple's* identity, not the statement's, so two tuples wrapping the
same statement (the same shared wrapper paragraph feeding two different
terminators, exactly the scenario `orchestrator.py`'s existing comment about
"several plans can share the same PERFORM edge" already describes) would
never dedupe against each other, causing the flag-check to be inserted
twice after the same line. Both sites must dedupe on `id(perform_statement)`
(the first tuple element), not `id(perform)` the tuple itself.

`find_terminator_plans`'s per-chain-perform validation loop (today: a single
call to `statement_top_level_problem` per `perform` in `chain_performs`)
branches on the tag:

- `nested=False`: calls `statement_top_level_problem` exactly as today — byte
  for byte unchanged, zero behavior change for the already-shipped,
  spike-verified top-level path.
- `nested=True`: calls `nested_chain_perform_problem`; a non-`None` reason
  refuses `UNSUPPORTED_TERMINATOR_LAYOUT` with a nesting-specific message
  (e.g. "an intermediate PERFORM {target} at line {line}, nested inside a
  conditional body, {reason} -- inserting the early-exit check there would
  {corrupt sibling code / land outside the conditional}").

`orchestrator.py`'s chain-check insertion loop branches the same way to
compute the insertion line: `nested=False` keeps using
`statement_span(perform, boundaries, last_line)` (the existing
`collect_boundaries`-derived coarse path); `nested=True` uses
`nested_chain_perform_problem`'s validated `(start, end)` span instead
(already guaranteed non-`None` here, since `find_terminator_plans` refused
anything where it wasn't). The actual `insert_lines_after` call and the
overall bottom-up, position-sorted merge with boundary-mock splice
operations are unchanged either way.

## Verification plan (spikes)

Per this project's established rigor (every fact in the original six-spike
design and the 2026-07-10 GO-TO investigation was settled by compiling and
running real GnuCOBOL 3.2 in the pinned Docker toolchain, never reasoned from
documentation alone — see `docs/2026-07-08-goback-stop-run-support-design.md`
and `docs/2026-07-10-goto-reachable-terminators-design.md`), this mechanism
needs new spikes before being trusted. None of the original six spikes tested
a `PERFORM` *itself* nested inside a conditional as a chain link — spike #2
tested the terminator's own nesting; spike #3 tested an unconditional
intermediate `PERFORM`. Planned spikes, `TERMDEMO`-style synthetic programs,
isolated worktree, `cobc`-compile-and-run:

| # | Shape | What it tests |
|---|---|---|
| N1 | `IF X PERFORM MIDDLE-PARA END-IF` as the chain link to a terminator, with a `DISPLAY` after the `IF` in the same paragraph | Flag-check inserted right after the nested `PERFORM` (before `END-IF`) correctly suppresses the trailing `DISPLAY` and unwinds further up the chain |
| N2 | Same shape, but `PERFORM` and `END-IF` share one physical line | Confirms this correctly refuses (`UNSUPPORTED_TERMINATOR_LAYOUT`) instead of inserting the check outside the conditional |
| N3 | `EVALUATE` `WHEN`/`WHEN OTHER` branch containing the chain-link `PERFORM` | Same propagation correctness inside an `EVALUATE` branch |
| N4 | Chain-link `PERFORM` nested inside an inline `PERFORM ... END-PERFORM` loop body, same paragraph | Confirms `EXIT PARAGRAPH` still unwinds the *whole* paragraph correctly from inside an inline loop — distinct from the already-proven-unsafe case (2026-07-09 correction) of an out-of-line `PERFORM` that *is* a loop over a different paragraph |
| N5 | Two levels of nesting (`IF` inside `IF`) as the chain link | Confirms the check lands in the innermost scope and still unwinds correctly all the way up |

If any spike surfaces unexpected `cobc` behavior — mirroring how the
looping-PERFORM bug (2026-07-09) and the GO-TO investigation's spike #4
failure were both discovered empirically, not predicted — this design is
revised before implementation proceeds, same decision-gate posture as the
GO-TO investigation doc.

## Out of scope

- A `PERFORM` nested inside another boundary statement's clause body
  (`in_boundary=True`) — permanent structural refusal, not deferred (see
  Design, step 2).
- `PERFORM ... THRU` as a nested chain edge — already excluded for top-level
  edges today (`thru_paragraph is None` requirement), unchanged.
- A looping out-of-line `PERFORM` (`perform_type != "SIMPLE"`) as a chain
  edge — already excluded, unchanged, orthogonal to this feature.
- `GO TO`-reachable terminators/chains, `SECTION`-scoped terminators/chains —
  unrelated axes, separately tracked (`GO TO` has its own investigation,
  `docs/2026-07-10-goto-reachable-terminators-design.md`, in flight as of
  this same date).

## Testing

- Unit (Docker-free): nested-edge detection in the new walker (each of
  IF/ELSE, EVALUATE, inline-PERFORM-loop nesting reachable as a chain edge);
  `nested_chain_perform_problem` line-sharing cases (N2-style: shares line
  with `END-IF`/`ELSE`/`WHEN`; owns its line correctly succeeds);
  `in_boundary=True` edges always refused regardless of layout — mirroring
  `test_refusal.py`/`test_terminator_reachability.py`'s existing structure.
- Integration (`@requires_docker`): N1-N5 become permanent regression
  fixtures, `test_terminator_support.py`-style, once proven — this is
  exactly the kind of empirically-load-bearing fact this codebase already
  treats as deserving a permanent compile-and-run test, not a
  design-session throwaway script.

## Docs sync

- `docs/2026-07-08-goback-stop-run-support-design.md`'s "Out of scope" bullet
  for conditionally-nested intermediate `PERFORM` marked resolved, pointing
  here.
- `README.md` known-limitations section and `.okf/analysis.md`/
  `.okf/splicer.md` concept rows updated to describe the extended chain
  detection and the new nested-span validation function.
- `docs/2026-07-06-real-world-readiness-audit.md` Finding 3's
  "conditionally-nested intermediate `PERFORM`s" sub-bullet marked resolved.
