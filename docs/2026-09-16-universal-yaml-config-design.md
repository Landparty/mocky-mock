# Universal `cobol.yml` project config — mockymock's layer

**Date:** 2026-09-16
**Status:** implemented
**Repos:** cobol-parser (the file format and reader), mocky-mock (this
document), cobol-analyzer (copybook paths in the editor)

## Problem

A COBOL shop using all three tools configures the same project three times:
`--copybook-path` on every `cobol-parser` and `mockymock` invocation (or in
`mockymock.toml`), and `cobolAnalyzer.copybookPaths` in VS Code settings.
The three drift, and a copybook that resolves on the command line fails to
resolve in the editor — or worse, resolves to a different member.

`mockymock.toml` (2026-09-15, see `2026-09-15-cli-ergonomics-design.md`)
solved half of it for this CLI alone. TOML was chosen there for "no new
dependency", not because YAML was rejected on merit; and a tool-specific
file cannot by construction be read by the other two tools.

## Decision

One file, `cobol.yml` (or `cobol.yaml`), at the project root, read by all
three. **The schema and the reader live in cobol-parser**, which is already a
hard dependency of this package — duplicating either here would create a
second schema to keep in step with the first, and the two drifting is exactly
what a single universal file exists to prevent.

```yaml
version: 1

project:            # shared by every tool
  copybook_path: [copybooks]
  seed: 42

mockymock:          # this CLI's own keys; overrides `project:`
  test_root: tests
  ai_mode: guided
```

`project:` supplies the settings shared with every other tool
(`copybook_path`, `seed`); `mockymock:` supplies this CLI's own
(`test_root`, `ai_mode`) and may override anything `project:` said — a
project can share one seed for parsing and pin a different one for test
generation.

## Layering with `mockymock.toml`

Both files are searched for **independently**, each walking from the start
directory up through its parents; the nearest of each wins its own search.
When both exist, the tool-specific file **overrides the universal one key by
key** — more specific beats more general.

The rejected alternative was first-match-wins across both, matching how
`mockymock.toml` already beats `pyproject.toml` within a directory. It fails
badly here: a `mockymock.toml` that sets only `seed` would silently discard a
`cobol.yml` that set `copybook_path`, `test_root` and `ai_mode`. Key-by-key
merging is why `_validated_values()` returns only the keys a file actually
sets rather than a fully-defaulted config.

Two independent walks (rather than one walk looking for either) is what makes
the normal monorepo shape work: a `cobol.yml` at the repo root and a
`mockymock.toml` in a subproject, both applying.

`MockymockConfig.sources` lists every file that contributed, base first;
`source` stays the file that had the last word, which is where
`skills mode --set` would write. `mockymock doctor` reports the whole chain,
since reporting only the winner would leave the other file invisible — the
exact question that check exists to answer.

## Version coordination

`cobolparser.config` lands in cobol-parser 1.10. The dependency floor here is
**deliberately not raised** for it: everything else in this package works on
1.7.7, and a project that never writes a `cobol.yml` should not be forced to
upgrade. `_universal_values()` soft-imports, and only when a `cobol.yml`
actually exists does it fail — with a message naming the version to install
and the alternative (move the settings into a `mockymock.toml`).

The discovery walk itself is implemented **here**, not delegated, precisely
so that case produces that message rather than the file being silently
skipped.

## `skills mode --set` against a `cobol.yml`

Refused, with the two lines to paste. Unlike the `pyproject.toml` refusal —
where writing a `mockymock.toml` alongside would *shadow* the whole
`[tool.mockymock]` table — a new `mockymock.toml` would layer over a
`cobol.yml` perfectly well. It is refused anyway: silently splitting a
project's settings across two files, when the entire point of the universal
one is to have a single place, is not a decision to make on the user's
behalf.

## Not changed

* Every existing invocation behaves identically. `mockymock.toml`,
  `[tool.mockymock]`, and explicit flags all keep their exact semantics.
* `timeout` remains deliberately non-config-overridable, in both files.
* Precedence at the call site is unchanged: explicit CLI flag > config file >
  built-in default.

## Tests

`tests/unit/test_cli_universal_config.py` — the universal layer, the
key-by-key merge, the two independent walks, the rejections, and the
`skills mode` refusal. `tests/unit/test_cli_config.py` continues to cover the
tool-specific path unchanged.
