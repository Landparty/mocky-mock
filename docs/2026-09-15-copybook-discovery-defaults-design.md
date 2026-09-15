# Fixing the first-run copybook trap (2026-09-15)

## Problem

Linting or running any program with copybooks and no `--copybook-path`
fails with a message that neither says the flag exists nor suggests
anything useful:

```
$ mockymock lint examples/real-world/ACCTMNT/ACCTMNT.cbl --cut ACCTMNT.cut
mockymock lint: copybook expansion failed: Copybook 'ACCTMAST' not found
in search paths: examples/real-world/ACCTMNT. Did you mean: ACCTMNT?
```

Two independent bugs compound into one bad first impression:

1. **mockymock never points cobol-parser's copybook search at the
   `copybooks/` directory every one of its own examples uses**
   (`examples/real-world/*/copybooks/*.cpy`, per
   `examples/real-world/README.md:22-23`, which tells the human to pass
   `--copybook-path examples/real-world/<PROGRAM>/copybooks` by hand
   every time). Nothing in `mockymock/cli/main.py` tries a `copybooks/`
   subdirectory next to the program before giving up.
2. **cobol-parser's did-you-mean suggests the program's own filename.**
   `suggest_similar_copybooks` (`cobol-parser/cobolparser/preprocess/path_resolver.py:126-156`)
   calls `get_available_copybooks`, whose `search_config.extensions`
   default is `[".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB", ""]`
   (`cobol-parser/cobolparser/preprocess/models.py:249-251`) -- the
   trailing `""` means "any extension," so every file in the search
   directory becomes a candidate, including `ACCTMNT.cbl` itself. That is
   why the suggestion for a missing `ACCTMAST` copybook is `ACCTMNT`, the
   program's own name one directory up from where the real copybook
   lives.

Neither bug is specific to `ACCTMNT` -- the same survey found it on all
15 of the `examples/real-world/` programs that use copybooks.

## Goals

- `mockymock` finds copybooks in the conventional places (a `copybooks/`
  sibling directory, and the program's own directory) with no flag
  needed, for the common case that motivated `--copybook-path` in the
  first place.
- When copybook resolution still fails, the message names the flag that
  fixes it and never suggests a non-copybook file.
- `--copybook-path` keeps working exactly as today and always wins over
  any default.

## Design

### mockymock-side: default search directories

In `mockymock/cli/main.py`, wherever `--copybook-path` is currently
collected into `copybook_paths` before being handed to cobol-parser's
`expand_copybooks`/`parse_cobol_with_expansion` (the call sites named in
`.okf/integration.md`), build the effective list as:

```
effective_paths = [
    *args.copybook_path,                 # explicit, always first (highest priority)
    program_dir / "copybooks",           # convention used by every example + README
    program_dir,                         # copybooks sometimes sit beside the .cbl
]
```

filtered to directories that actually exist, and deduplicated
preserving order (`dict.fromkeys` over resolved absolute paths). This is
additive to the search list cobol-parser already receives, not a
replacement -- an explicit `--copybook-path` still searches first and a
`copybooks/` directory that doesn't exist is silently skipped, so a
program with no copybooks pays no cost.

This one change, with no cobol-parser fix needed, makes `mockymock lint`/`run`
work on every `examples/real-world/` program with zero flags -- closing
Finding 5 of `docs/2026-09-05-project-deep-audit.md` (shipped examples
refused by the gate while the README claims they pass) at the same time,
since that finding's root cause is exactly "the flag was never passed
where the README's own instructions say it must be."

### mockymock-side: name the flag on failure

Independent of the default-directory change (defense in depth for a
program whose copybooks live somewhere else entirely): catch the
resolution failure at the `mockymock` CLI boundary --
`copybook_expander`'s exception already carries the searched-paths list
and any suggestions (`_normalize.py:136-145`) -- and append one line
mockymock controls directly:

```
mockymock lint: copybook expansion failed: Copybook 'ACCTMAST' not found
in search paths: examples/real-world/ACCTMNT, examples/real-world/ACCTMNT/copybooks.
Did you mean: ...?
    Pass its location with --copybook-path <dir> (repeatable), or add a
    [tool.mockymock] copybook_path entry -- see
    docs/2026-09-15-cli-ergonomics-design.md's config file.
```

This wraps the upstream exception's message rather than replacing it, so
cobol-parser's own text (search paths actually tried, any valid
suggestion) stays visible; mockymock only appends the actionable next
step, in the same `_check_input_files`-style boundary used for other
early, friendly CLI errors (`mockymock/cli/main.py`'s `_check_input_files`
pattern).

### Upstream in cobol-parser: stop suggesting non-copybook files

Tracked as a coordinated but separately-landed fix in
`Landparty/cobol-parser`, since it is a one-line, narrowly-scoped
correction to shared logic mockymock does not own:

`suggest_similar_copybooks` should restrict its candidate pool to files
whose extension marks them as copybooks, not "any file cobol-parser
would accept as a copybook body if you pointed it at one by name" (the
current `""` catch-all extension exists so a copybook *without* an
extension resolves as a member -- that's a legitimate resolution
behavior, just the wrong pool for a *typo suggestion*). Concretely, add a
`suggestion_extensions` parameter to `get_available_copybooks`/
`suggest_similar_copybooks` defaulting to `[".cpy", ".CPY"]` -- the
unambiguous copybook extensions -- used only by the did-you-mean path;
full resolution (`resolve_copybook_path` and friends) keeps its existing
`extensions` default unchanged, so this does not change what actually
resolves, only what gets suggested when nothing does. A `.cbl`/`.cob`
file sitting in a copybook search directory (the exact `ACCTMNT.cbl`
case) then never surfaces as a "did you mean."

Since this repo consumes cobol-parser as a versioned dependency, the
mockymock-side changes above ship independently and do not block on the
upstream fix landing; mockymock's own message-wrapping (previous section)
degrades gracefully either way, since it appends to whatever suggestion
text upstream provides rather than parsing or validating it.

## Implementation steps (mocky-mock repo)

1. `mockymock/cli/main.py` (or a new small helper in
   `mockymock/cli/discovery.py`, alongside the sibling-file resolution
   from `2026-09-15-cli-ergonomics-design.md` -- copybook and program
   discovery are the same category of "guess the conventional layout"
   logic and belong together): `effective_copybook_paths(program_path,
   explicit_paths) -> list[Path]` implementing the ordered,
   existence-filtered, deduplicated list above.
2. Thread `effective_copybook_paths(...)` into every call site that
   currently passes `args.copybook_path` straight through: `_cmd_run`,
   `_cmd_lint`, `_cmd_generate`, `_cmd_mutate`, `_cmd_debug`, `_cmd_export`,
   `_cmd_analyze`, `_cmd_fixtures` (grep `copybook_path` in
   `mockymock/cli/main.py` for the full call-site list before starting,
   to avoid missing one).
3. Wrap the copybook-expansion exception at the CLI boundary (one place,
   likely already-shared error handling near `_check_input_files`) to
   append the actionable-flag line.
4. Unit tests (`tests/unit/`, Docker-free): `effective_copybook_paths`
   with (a) no copybooks anywhere -- unchanged list, (b) a `copybooks/`
   sibling present -- appended, (c) an explicit `--copybook-path` that
   duplicates the default -- appears once, first.
5. Integration test: re-run every `examples/real-world/*/` program's
   `lint` **without** `--copybook-path` and assert it now resolves (this
   directly re-verifies Finding 5 of the 2026-09-05 audit) -- add this as
   a parametrized case alongside the existing enterprise-corpus sweep
   (`tests/unit/test_enterprise_corpus.py`'s pattern) rather than one-off
   scripts.
6. Update `examples/real-world/README.md` to drop the now-unnecessary
   manual `--copybook-path` instruction (keep a note that it's still
   needed for copybooks that live somewhere other than `copybooks/` or
   the program's own directory).
7. `.okf/integration.md` and `.okf/log.md`: document the new default
   search behavior and link the upstream cobol-parser issue/PR for the
   suggestion-pool fix.

## Implementation steps (cobol-parser repo, coordinated)

1. `cobolparser/preprocess/path_resolver.py`: add
   `suggestion_extensions` parameter to `get_available_copybooks`
   (default `None`, meaning "use `search_config.extensions`" --
   preserves current behavior for any direct caller) and to
   `suggest_similar_copybooks` (default `(".cpy", ".CPY")`, passed
   through as the override).
2. Unit test: `suggest_similar_copybooks` over a directory containing
   `ACCTMAST.cpy` and `ACCTMNT.cbl` no longer suggests `ACCTMNT` for a
   missing `ACCTMAST` reference; still suggests `ACCTMAST` for a
   near-miss like `ACCTMSTR`.
3. `CHANGELOG.md` Unreleased entry; this is a behavior-narrowing change
   to a suggestion list only, not a resolution-affecting change, so it
   is not a breaking change to the public API surface documented in
   `interface-contract.md`.

## Testing plan

Covered inline in each Implementation steps section above. The end-to-end
acceptance check for this whole design is: `mockymock lint` (no
`--copybook-path`) against every `examples/real-world/*/` program exits 0
(or with only expected `UNMOCKED_*`/refusal findings unrelated to
copybook resolution), and no did-you-mean suggestion in the corpus ever
names a `.cbl`/`.cob` file.

## Backward compatibility

The mockymock-side default is purely additive to the search list and
only activates for a directory that exists, so a program with no
`copybooks/` subdirectory behaves identically to today. The
cobol-parser-side change narrows a suggestion list, not resolution
behavior -- no program that resolves today stops resolving, and no
suggestion that was a real copybook stops being suggested.
