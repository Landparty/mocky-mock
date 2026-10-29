"""Suite <-> program pairing and directory-wide `.cut` discovery.

A suite finds its program through one ordered lookup (first match wins,
see `resolve_program`):

1. `program`  -- the suite's own `PROGRAM "<path>"` line, relative to the
   .cut file's folder. Any file name works when it is present.
2. `sibling`  -- `<dir>/<base>.cbl` (or .cob/.CBL/.COB) next to the suite,
   the original rule, so every existing suite keeps working.
3. `mirror`   -- a suite under the tests folder maps to the same relative
   folder under the source root: tests/pay/PAYROLL.cut -> src/pay/PAYROLL.cbl.
4. `unique`   -- the only `<base>.cbl` anywhere under the source root.

`<base>` is the .cut file name up to its FIRST dot, so `PAYROLL.cut` and
`PAYROLL.errors.cut` both belong to PAYROLL: that is how one program gets
several suites. The VS Code extension asks `mockymock suites --json` for
these answers instead of re-implementing them.

See docs/2026-10-14-multi-suite-layout-design.md (the layout) and
docs/2026-09-15-cli-ergonomics-design.md (the original sibling rule).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mockymock.cli.config import MockymockConfig

# Order matters: .cbl is tried before .cob when both would exist (they
# never should for the same stem, but the order is deterministic either
# way). Matches mocky-mock-vscode's COBOL_SOURCE_EXTENSIONS list.
COBOL_SOURCE_EXTENSIONS = (".cbl", ".cob", ".cobol", ".CBL", ".COB", ".COBOL")

# Directories a directory-wide `.cut` scan skips. Mirrors
# mocky-mock-vscode's CUT_DISCOVERY_EXCLUDE_GLOB so CLI and editor
# discovery agree on what "the project's own test suites" means.
CUT_DISCOVERY_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)


class DiscoveryError(Exception):
    """A program or `.cut` path could not be inferred."""


#: The folder new suites go in when no config names one.
DEFAULT_TESTS_DIR = "tests"
#: The source root when no config names one and this folder exists.
DEFAULT_SOURCE_DIR = "src"


@dataclass(frozen=True)
class ProjectLayout:
    """Where a project keeps its programs and its suites. All absolute."""

    root: Path
    tests_dir: Path
    source_root: Path


def project_layout(
    config: MockymockConfig | None = None, start_dir: Path | None = None
) -> ProjectLayout:
    """The layout for the project `config` was loaded for. The root is the
    folder of the config file that had the last word, else `start_dir`
    (default cwd). `test_root`/`source_root` in that config are already
    absolute (resolved against the file that declared them); with no
    `test_root` the tests folder is `<root>/tests`, with no `source_root`
    the source root is the project root itself."""
    if config is not None and config.source is not None:
        root = config.source.parent.resolve()
    else:
        root = (start_dir or Path.cwd()).resolve()
    # MockymockConfig.test_root is "." exactly when no file set it (an
    # explicit value is always stored as an absolute path).
    if config is not None and config.test_root != ".":
        tests_dir = Path(config.test_root).resolve()
    else:
        tests_dir = root / DEFAULT_TESTS_DIR
    if config is not None and config.source_root:
        source_root = Path(config.source_root).resolve()
    elif (root / DEFAULT_SOURCE_DIR).is_dir():
        # The common layout: mirror src/pay/PAY.cbl to tests/pay/PAY.cut,
        # not tests/src/pay/PAY.cut.
        source_root = root / DEFAULT_SOURCE_DIR
    else:
        source_root = root
    return ProjectLayout(root=root, tests_dir=tests_dir, source_root=source_root)


def suite_base_name(cut_path: Path) -> str:
    """`PAYROLL.errors.cut` -> `PAYROLL`: the file name up to its first dot."""
    return cut_path.name.split(".", 1)[0]


def read_program_line(cut_path: Path) -> str | None:
    """The path on the suite's `PROGRAM "<path>"` line, or None. Only looks
    before the first TESTCASE, where the parser allows the line. Reads raw
    text rather than parsing the whole suite, so a suite with a syntax
    error further down still pairs (and lint can then report that error
    against the right program)."""
    from mockymock.dsl.parser import PROGRAM_RE

    try:
        text = cut_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("TESTCASE"):
            break
        if (m := PROGRAM_RE.match(line)) is not None:
            return m.group("path")
    return None


def _is_within(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


@lru_cache(maxsize=8)
def _programs_by_stem(source_root: str) -> dict[str, tuple[Path, ...]]:
    """Every COBOL source under `source_root`, keyed by upper-cased stem,
    skipping CUT_DISCOVERY_EXCLUDE_DIRS. Cached per process: `suites` and
    the directory-wide `run`/`lint` resolve many suites against one tree."""
    index: dict[str, list[Path]] = {}
    extensions = {e.lower() for e in COBOL_SOURCE_EXTENSIONS}
    for dirpath, dirnames, filenames in os.walk(source_root):
        dirnames[:] = sorted(d for d in dirnames if d not in CUT_DISCOVERY_EXCLUDE_DIRS)
        for filename in sorted(filenames):
            stem, ext = os.path.splitext(filename)
            if ext.lower() in extensions:
                index.setdefault(stem.upper(), []).append(Path(dirpath) / filename)
    return {k: tuple(v) for k, v in index.items()}


def _first_existing(folder: Path, base: str) -> Path | None:
    for ext in COBOL_SOURCE_EXTENSIONS:
        candidate = folder / f"{base}{ext}"
        if candidate.is_file():
            return candidate
    return None


def resolve_program(
    cut_path: Path, layout: ProjectLayout | None = None
) -> tuple[Path, str]:
    """The program `cut_path` tests and which rule found it (`program`,
    `sibling`, `mirror` or `unique`, see the module docstring). Raises
    `DiscoveryError` naming every place it looked."""
    layout = layout or project_layout()
    cut_abs = cut_path.resolve()
    base = suite_base_name(cut_path)

    declared = read_program_line(cut_path)
    if declared is not None:
        # An explicit claim never falls through to a guess: a typo here
        # must fail, not quietly pair the suite with some other program.
        program = Path(declared)
        if not program.is_absolute():
            program = cut_path.parent / program
        if not program.is_file():
            raise DiscoveryError(
                f"{cut_path}: PROGRAM {declared!r} does not exist "
                f"(resolved to {program})"
            )
        return program, "program"

    tried: list[str] = []
    # The whole stem first: a pre-existing `A.B.cut` beside `A.B.cbl`
    # paired that way before base names existed.
    for stem in dict.fromkeys((cut_path.stem, base)):
        sibling = _first_existing(cut_path.parent, stem)
        if sibling is not None:
            return sibling, "sibling"
        tried.extend(
            str(cut_path.parent / f"{stem}{ext}") for ext in COBOL_SOURCE_EXTENSIONS
        )

    # The whole stem before the first-dot base in the mirror and unique
    # rules too: `generate` names a suite after the program's full stem, so
    # `tests/pay/PAY.V2.cut` is `src/pay/PAY.V2.cbl`'s (issue #289).
    stems = tuple(dict.fromkeys((cut_path.stem, base)))
    if layout.tests_dir != layout.source_root and _is_within(
        cut_abs.parent, layout.tests_dir
    ):
        mirrored_dir = layout.source_root / cut_abs.parent.relative_to(layout.tests_dir)
        for stem in stems:
            mirrored = _first_existing(mirrored_dir, stem)
            if mirrored is not None:
                return mirrored, "mirror"
            tried.append(str(mirrored_dir / f"{stem}.cbl") + " (and .cob)")

    by_stem = _programs_by_stem(str(layout.source_root))
    for stem in stems:
        matches = by_stem.get(stem.upper(), ())
        if len(matches) == 1:
            return matches[0], "unique"
        if len(matches) > 1:
            listed = ", ".join(str(m) for m in matches)
            raise DiscoveryError(
                f"{cut_path}: {len(matches)} programs named {stem} under "
                f'{layout.source_root} ({listed}); add a PROGRAM "<path>" line '
                f"after TESTSUITE to say which one this suite tests"
            )
    tried.append(f"any {base}.cbl under {layout.source_root}")
    raise DiscoveryError(
        f"no COBOL program found for {cut_path} (tried: {'; '.join(tried)}); "
        f'add a PROGRAM "<path>" line after TESTSUITE, or pass the program '
        f"path explicitly"
    )


def resolve_program_path(
    explicit: str | None, cut_path: Path, layout: ProjectLayout | None = None
) -> Path:
    """`explicit` wins unconditionally; otherwise `resolve_program`."""
    if explicit is not None:
        return Path(explicit)
    return resolve_program(cut_path, layout)[0]


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return False


def find_suites(program_path: Path, layout: ProjectLayout | None = None) -> list[Path]:
    """Every discovered `.cut` file whose lookup lands on `program_path`,
    sorted. Scans the project root, plus the program's own folder when it
    lies outside the root (a program passed by absolute path)."""
    layout = layout or project_layout()
    candidates = set(project_cut_files(layout))
    if not _is_within(program_path.resolve().parent, layout.root):
        candidates.update(p for p in program_path.parent.glob("*.cut") if p.is_file())
    found = []
    for cut in candidates:
        try:
            program, _ = resolve_program(cut, layout)
        except DiscoveryError:
            continue
        if _same_file(program, program_path):
            found.append(cut)
    return sorted(found)


def resolve_cut_path(
    explicit: str | None, program_path: Path, layout: ProjectLayout | None = None
) -> Path:
    """`explicit` wins; otherwise the program's one suite. Raises
    `DiscoveryError` when it has none, or several (naming them, since the
    caller then needs `--cut`)."""
    if explicit is not None:
        return Path(explicit)
    suites = find_suites(program_path, layout)
    if len(suites) == 1:
        return suites[0]
    if not suites:
        raise DiscoveryError(
            f"no .cut file found for {program_path} (looked beside it and "
            f"under {(layout or project_layout()).root}); pass --cut explicitly"
        )
    listed = ", ".join(str(s) for s in suites)
    raise DiscoveryError(
        f"{program_path} has {len(suites)} suites ({listed}); pass --cut "
        f"to pick one"
    )


def default_suite_path(
    program_path: Path, layout: ProjectLayout | None = None, name: str | None = None
) -> Path:
    """Where a new suite for `program_path` goes: `<tests>/<folder>/PROG.cut`
    (or `PROG.<name>.cut`), mirroring the program's folder under the source
    root. Falls back to beside the program when the program lies outside
    the source root (nothing to mirror), or when an unnamed sibling suite
    `PROG.cut` already exists -- that project uses the sibling layout, and
    a second default suite elsewhere would be a surprise."""
    layout = layout or project_layout()
    stem = program_path.stem
    file_name = f"{stem}.{name}.cut" if name else f"{stem}.cut"
    sibling = program_path.parent / file_name
    if not name and sibling.is_file():
        return sibling
    program_dir = program_path.resolve().parent
    if layout.tests_dir == layout.source_root or not _is_within(
        program_dir, layout.source_root
    ):
        return sibling
    return layout.tests_dir / program_dir.relative_to(layout.source_root) / file_name


def effective_copybook_paths(
    program_path: Path, resolved_paths: list[str]
) -> list[str]:
    """Append `program_path`'s own `copybooks/` subdirectory -- the
    layout every example under `examples/real-world/` uses -- and the
    other conventional copybook folders beside it or beside its folder
    (`_default_copybook_dirs`) to
    `resolved_paths` (already resolved from an explicit `--copybook-path`
    flag or the project config file, see `config.resolve_copybook_paths`),
    when it exists and isn't already present. Never reorders or removes
    anything the caller already resolved -- this is an additive fallback,
    tried after everything explicit, so a program with copybooks
    somewhere else entirely is unaffected and a program with none at all
    pays no cost. See docs/2026-09-15-copybook-discovery-defaults-design.md.

    Deliberately does NOT also default to `program_path`'s own directory
    (the design doc's original second fallback): that directory always
    exists trivially, so adding it unconditionally would turn every
    COPY-bearing program into an implicit copybook search even when none
    was ever configured -- observed in practice as
    test_fixtures_copy_bearing_program_without_copybook_path_refuses
    breaking, because a program with an unresolvable COPY and truly no
    copybook path configured is supposed to fall through unexpanded and
    be caught by the structural UNRESOLVED_COPYBOOK gate, not attempt
    (and fail) expansion against its own source directory."""
    result = list(resolved_paths)
    seen: set[Path] = set()
    for entry in result:
        try:
            seen.add(Path(entry).resolve())
        except OSError:  # pragma: no cover - unresolvable path, leave as-is
            continue
    for default_dir in _default_copybook_dirs(program_path):
        if default_dir.is_dir():
            resolved_default = default_dir.resolve()
            if resolved_default not in seen:
                seen.add(resolved_default)
                result.append(str(default_dir))
    return result


#: Copybook directory names a source tree conventionally uses, beside the
#: program (`copybooks/`, the examples' layout) or beside the program's
#: own folder (`cobol/` + `copybook/`, the usual mainframe export --
#: legacy-application's INTCALC was refused UNRESOLVED_COPYBOOK until
#: `--copybook-path ../copybook` was passed).
#: `dclgen/` and `include/` hold the members `EXEC SQL INCLUDE` names (the
#: DCLGEN output a DB2 shop exports beside its copylib).
_COPYBOOK_DIR_NAMES = (
    "copybooks",
    "copybook",
    "copylib",
    "copy",
    "cpy",
    "dclgen",
    "include",
)


def _default_copybook_dirs(program_path: Path) -> list[Path]:
    """Where `effective_copybook_paths` looks unasked: each of
    `_COPYBOOK_DIR_NAMES` under the program's folder, then beside it. A
    directory only counts when it exists, so neither the program's own
    folder nor its parent is ever searched itself (see the docstring
    above)."""
    folder = program_path.parent
    return [folder / name for name in _COPYBOOK_DIR_NAMES] + [
        folder.parent / name for name in _COPYBOOK_DIR_NAMES
    ]


def copybook_not_found_hint(exc: BaseException | None = None) -> str:
    """The actionable follow-up line appended after a
    cobolparser.preprocess.CopybookNotFoundError's own message (which
    already names every path it searched). Formatted as a 4-space
    continuation line, matching how the rest of this CLI already renders
    a multi-line problem (see `_cmd_lint`'s "  " prefix convention).

    Given the error itself, a second line names any file that looks like
    the member but that the search cannot match (`near_miss_copybooks`):
    a mainframe export often lands as `gttlbi0a.copy` or `DMTREN0A.dcl`,
    and on a case-sensitive filesystem with an extension cobol-parser
    does not try, no search path would ever find it."""
    # Names cobol.yml first: it is the file the rest of the tool family
    # (cobol-parser, the COBOL Analyzer extension) reads too, so one entry
    # there fixes every tool at once -- see `config.py`'s module docstring.
    hint = (
        "    Pass its location with --copybook-path <dir> (repeatable), or "
        "set copybook_path under project: in cobol.yml (shared with "
        "cobol-parser) or in mockymock.toml / [tool.mockymock]."
    )
    if exc is not None and not hasattr(exc, "copybook_name"):
        exc = exc.__cause__
    member = getattr(exc, "copybook_name", None)
    if not member:
        return hint
    near = near_miss_copybooks(member, list(getattr(exc, "search_paths", [])))
    if near:
        hint += (
            f"\n    Found {', '.join(str(p) for p in near)}, named like "
            f"'{member}' but not matched: the member is looked up as "
            f"written, with extension {', '.join(_MATCHED_EXTENSIONS)} or "
            f"none -- copy or rename it to {member}.cpy in a searched "
            f"directory."
        )
    return hint


#: The extensions cobol-parser's copybook search tries, after the bare
#: member name (cobolparser.preprocess's path resolver).
_MATCHED_EXTENSIONS = (".cpy", ".cbl", ".cob")
_SEARCHED_SUFFIXES = frozenset(
    _MATCHED_EXTENSIONS + tuple(e.upper() for e in _MATCHED_EXTENSIONS)
)
#: How many files `near_miss_copybooks` lists before it stops looking.
_NEAR_MISS_LIMIT = 5


def near_miss_copybooks(member: str, search_paths: list[str]) -> list[Path]:
    """Files whose stem is `member` in any letter case, under each
    searched directory or a conventional copybook folder beside it
    (`_COPYBOOK_DIR_NAMES`), that the search did not match: a different
    case, or an extension cobol-parser does not try (`.copy`, `.dcl`,
    `.txt`). One directory level only, so a large tree is never walked;
    at most `_NEAR_MISS_LIMIT` results, sorted."""
    wanted = member.casefold()
    dirs: dict[Path, None] = {}
    for entry in search_paths:
        base = Path(entry)
        dirs[base] = None
        for name in _COPYBOOK_DIR_NAMES:
            dirs[base.parent / name] = None
    found: list[Path] = []
    for folder in dirs:
        try:
            children = sorted(folder.iterdir()) if folder.is_dir() else []
        except OSError:  # pragma: no cover - unreadable folder
            continue
        for child in children:
            name = child.name
            stem, dot, ext = name.partition(".")
            if stem.casefold() != wanted or not child.is_file():
                continue
            if stem == member and (not dot or f".{ext}" in _SEARCHED_SUFFIXES):
                continue  # the search would have matched this one
            found.append(child)
            if len(found) >= _NEAR_MISS_LIMIT:
                return found
    return found


def project_cut_files(layout: ProjectLayout) -> list[Path]:
    """Every `.cut` file of the project: those under its root, plus those
    under its tests folder when `test_root` points outside the root
    (`test_root = "../qa-tests"`, an absolute CI path) -- the folder
    `generate` writes new suites into, so a program-only command must find
    them there too (issue #294). Sorted, each file once."""
    found = {path.resolve(): path for path in discover_cut_files(layout.root)}
    if not _is_within(layout.tests_dir.resolve(), layout.root.resolve()):
        for path in discover_cut_files(layout.tests_dir):
            found.setdefault(path.resolve(), path)
    return sorted(found.values())


def discover_cut_files(root: Path) -> list[Path]:
    """Every `.cut` file under `root`, sorted for deterministic output,
    skipping `CUT_DISCOVERY_EXCLUDE_DIRS`. Returns an empty list (never
    raises) when `root` has no `.cut` files or doesn't exist."""
    if not root.is_dir():
        return []
    results = []
    for path in root.rglob("*.cut"):
        # Only the parts *below* `root` are subject to the exclude list:
        # the root itself may legitimately live under a `build/` or
        # `dist/` (an absolute test_root, a CI checkout path), and that
        # must not silently empty the scan.
        if any(
            part in CUT_DISCOVERY_EXCLUDE_DIRS
            for part in path.relative_to(root).parts[:-1]
        ):
            continue
        results.append(path)
    return sorted(results)
