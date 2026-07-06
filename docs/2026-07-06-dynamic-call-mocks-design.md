# Dynamic CALL mocks — design

2026-07-06. Extends the v2 all-boundaries design
(`2026-07-05-mock-all-boundaries-design.md`), which left `DYNAMIC_CALL`
refused as "target unknown at parse time; still future work".

## 1. The insight that makes this cheap

mockymock never *links* a mocked CALL: the splicer comments the whole CALL
statement out and replaces it with an EVALUATE dispatch block. Nothing at
runtime resolves a program name, so "target unknown at parse time" is not
actually a blocker — what the machinery needs is a *static match key* for
the site, and a dynamic `CALL WS-PGM-NAME` has a perfectly good one: the
identifier it calls through. cobolparser already exposes it (verified
empirically against cobolparser 1.1.0/1.2.0: parsing
`CALL WS-PGM-NAME USING ...` yields `CallStatement.called_program ==
"WS-PGM-NAME"`, `is_dynamic == True`).

Per-target behavior stays expressible without any new machinery because a
mock body is ordinary COBOL running in the program's own WORKING-STORAGE:
it can read the identifier's runtime value and branch on it
(`IF WS-PGM-NAME = "PGMA" ... END-IF`), exactly the way READ mocks already
branch on their tally.

## 2. DSL surface

The key for a dynamic call site is the identifier *name*, a bare COBOL
word — so the syntax follows the file-op precedent (bare word) rather than
the static-CALL precedent (quoted literal):

```
MOCK CALL WS-PGM-NAME          *> dynamic: CALLs through WS-PGM-NAME
    IF WS-PGM-NAME = "PGMA"
        MOVE 0 TO WS-RC
    ELSE
        MOVE 8 TO WS-RC
    END-IF
END-MOCK
...
VERIFY CALL WS-PGM-NAME WAS CALLED 2 TIMES
```

- `MOCK CALL "PGMA"` (quoted) keeps meaning "static CALL with literal
  `'PGMA'`"; `MOCK CALL WS-PGM-NAME` (bare) means "dynamic CALL through
  identifier WS-PGM-NAME". Quoting is the disambiguator, consistent with
  the existing quoted-vs-bare split in the grammar.
- Bare keys are uppercased at parse time (COBOL identifiers are
  case-insensitive), like file-op keys.
- `MOCK MQ` stays quoted-only: MQ is by definition invoked through static
  CALLs. A dynamic call that happens to dispatch to an MQ verb is just a
  dynamic CALL.
- `VERIFY CALL <bare-name> WAS CALLED|PERFORMED ...` mirrors the mock. The
  v1 back-compat form `VERIFY "X"` stays static-CALL.
- Tally field: `UT-CALL-<IDENTIFIER>-TALLY` (distinct from static CALL's
  v1-compat `UT-<NAME>-TALLY` shape; the registry's collision suffixing
  covers pathological overlaps as usual).

## 3. Internal model: a distinct category

A new `MockCategory.DYNCALL` (never written in `.cut` files — the surface
keyword is still `CALL`; the parser maps bare-key CALL to it). Rationale
over reusing `MockCategory.CALL` with a flag:

- Everything downstream — `directive_matches_site`, the `(category, key)`
  tuples in `all_mock_keys()`, `TallyRegistry`, the driver's declared-set
  check — switches on category and keys tuples by `(category, key)`.
  A flag would either change the tuple shape everywhere or let
  `MOCK CALL "X"` and `MOCK CALL X` collide into one tally/verify slot.
- Matching semantics genuinely differ: quoted keys match a static site's
  literal exactly (case-sensitive); bare keys match the dynamic site's
  uppercased identifier. With a distinct category, the existing default
  branch of `directive_matches_site` (`key.upper() in site.keys`) already
  implements dynamic matching — the category identity check does the rest.
- Fail-closed cross-matching for free: a quoted directive can never match
  a dynamic site (category mismatch → `UNMATCHED_MOCK` /
  `UNMOCKED_CALL`), and vice versa.

Cosmetics: `MockDirective.describe()` and the driver's VERIFY-fail
DISPLAY print the `.cut`-level keyword `CALL`, not `DYNCALL` (a
`MockCategory.keyword` property returns `"CALL"` for DYNCALL, else
`value`).

## 4. Changes by module

| Module | Change |
|--------|--------|
| `dsl/model.py` | `MockCategory.DYNCALL`; `keyword` property; `describe()` prints `CALL <bare-key>` |
| `dsl/parser.py` | bare-key `MOCK CALL <name>` / `VERIFY CALL <name>` → DYNCALL; error-message text updated |
| `analysis/mock_surface.py` | dynamic CallStatement with a captured identifier → `BoundarySite(category=DYNCALL, label="dynamic CALL", keys=(identifier.upper(),))`; identifier-less dynamic CALL keeps `category=None` (fail closed) |
| `analysis/refusal.py` | `_UNMOCKED_CODES[DYNCALL] = "UNMOCKED_CALL"`; the `DYNAMIC_CALL` refusal now fires only for identifier-less sites, message says so |
| `splicer/naming.py` | DYNCALL tally body sanitizes `CALL <key>` → `UT-CALL-<KEY>-TALLY` |
| `splicer/source_map.py` | `_VERB_TERMINATORS[DYNCALL] = "END-CALL"` (nested dynamic calls splice like nested static ones) |
| `splicer/driver.py` | VERIFY-fail DISPLAY uses `category.keyword` |
| `dsl/generator.py` | scaffolds `MOCK CALL <identifier>` with the CALL placeholder body (`MOVE 0 TO RETURN-CODE`) |
| `cli/main.py` | no change: identifier-carrying dynamic sites leave the unsupported-boundaries listing automatically because they are no longer `category=None` |

`injector.py`, `orchestrator.py`, `reset.py`, `stub_writer.py`, the report
layer: untouched — all category-agnostic.

## 5. Semantics and fail-closed edges

- **Matching is per-identifier, not per-target-program.** Two dynamic
  sites calling through the same identifier are both matched by one
  directive (same as two `OPEN INFILE` statements today); sites through
  different identifiers need their own directives.
- An unmocked reachable dynamic call refuses with `UNMOCKED_CALL` (same
  code as static — the message's `dynamic CALL` label and identifier key
  distinguish it).
- A dynamic CALL whose identifier cobolparser fails to capture
  (`called_program` empty) stays `category=None` → `DYNAMIC_CALL` refusal.
- One directive matching several same-identifier sites: allowed (site-level
  dispatch handles each site; tallies aggregate), same as every other
  category. Several directives matching one site: `AMBIGUOUS_MOCK`,
  unchanged.
- Nested dynamic calls follow the nested-mock-target rules verbatim
  (validated span or precise refusal).
- `VERIFY CALL <name>` with no matching mock: `VERIFY_WITHOUT_MOCK`,
  unchanged mechanics.

## 6. Testing

- Unit: parser round-trips (bare vs quoted vs MQ), describe/keyword,
  tally naming, surface classification (identifier captured / missing,
  nested), refusal matrix (mocked-passes / unmocked-refuses /
  cross-quoting never matches / keyless refuses DYNAMIC_CALL), generator
  scaffold, injector dispatch golden.
- Integration (Docker): fixture program driving one dynamic CALL to two
  different runtime targets from one identifier (mock body branches on the
  identifier), plus a USING parameter the mock fills; asserts EXPECT +
  VERIFY ... 2 TIMES end-to-end through GnuCOBOL.
