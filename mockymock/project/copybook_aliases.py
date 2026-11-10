"""Member-name aliasing for copybooks the search cannot match as written.

cobol-parser looks a `COPY GTTLBI0A` member up as `GTTLBI0A` with one of
`.cpy`/`.cbl`/`.cob` (either case) or no extension. A mainframe export
seldom lands like that: `gttlbi0a.copy`, `DMTREN0A.dcl`, `Gttlbi0a.txt`.
On a case-sensitive filesystem no search path ever finds those, and every
program that copies one is refused UNRESOLVED_COPYBOOK.

Rather than reimplement copybook resolution here, `stage_copybook_aliases`
gives each such file the name the search does try (`GTTLBI0A.cpy`) in a
staging directory, which `_apply_config_to_args` appends after every
other search path. Every consumer of the copybook path list -- the
expansion, the layout index, the static checks, the SQLCA lookup -- then
finds it the ordinary way, and a real `GTTLBI0A.cpy` anywhere earlier in
the list still wins.

Two sources feed the staging directory:

* **automatic**: in each searched directory (one level, never walked), a
  file whose name before its first dot matches no member as written but
  whose extension is in `copybook_extensions` (any case) is staged under
  its upper-cased stem.
* **explicit**: `copybook_aliases` maps a member name to a file, for the
  exports whose file name is not the member name at all.

The staging directory sits under the system temp folder, named by a
digest of what it holds, so an unchanged copylib is staged once and
reused. Files are hard-linked where the filesystem allows and copied
otherwise: a symlink would resolve outside the staging directory, which
cobol-parser's path-traversal check rejects.

Beside each staging directory, `<digest>.sources` lists the files it was
staged from, so `mockymock clean` can remove the copies of one project's
copybooks (`staged_directories_for`) without touching another's.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

#: The extensions an unmatched file may carry and still be staged, compared
#: without regard to case. `""` is a file with no extension at all (a PDS
#: member downloaded verbatim, in lower case). The first three are the ones
#: cobol-parser already tries, listed so a lower-case `gttlbi0a.cpy` is
#: staged too.
DEFAULT_COPYBOOK_EXTENSIONS: tuple[str, ...] = (
    ".cpy",
    ".cbl",
    ".cob",
    ".copy",
    ".cblcpy",
    ".dcl",
    ".dclgen",
    ".inc",
    ".txt",
    "",
)

#: What cobol-parser's search already matches when the stem is written
#: exactly as the member (its `CopybookSearchPath.extensions` default).
_RESOLVER_EXTENSIONS = frozenset({".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB"})

#: Where staging directories live. A module attribute so tests can point
#: it at a temporary folder.
STAGING_ROOT = Path(tempfile.gettempdir()) / "mockymock-copybook-aliases"


#: Suffix of the manifest written beside each staging directory.
MANIFEST_SUFFIX = ".sources"


def manifest_path(staged: Path) -> Path:
    """The `<digest>.sources` file listing what `staged` was built from."""
    return staged.with_name(staged.name + MANIFEST_SUFFIX)


def _split_name(name: str) -> tuple[str, str]:
    """`gttlbi0a.copy` -> (`gttlbi0a`, `.copy`); a name with no dot has
    extension `""`. Split at the first dot, like `near_miss_copybooks`,
    so `MEM.cpy.txt` is member `MEM` with extension `.cpy.txt`."""
    stem, dot, ext = name.partition(".")
    return stem, f".{ext}" if dot else ""


def _resolver_matches(stem: str, ext: str) -> bool:
    """Whether cobol-parser's own search finds this file for member
    `stem.upper()`: the stem already upper case, with an extension it
    tries or none."""
    return stem == stem.upper() and (ext == "" or ext in _RESOLVER_EXTENSIONS)


def automatic_aliases(
    search_paths: list[str], extensions: tuple[str, ...]
) -> dict[str, Path]:
    """Member name -> file, for each file in a searched directory that the
    search would miss but whose extension is in `extensions`. The first
    directory in search order wins a member, and within a directory the
    first file in sorted order, so the result never depends on listing
    order."""
    wanted = {ext.casefold() for ext in extensions}
    found: dict[str, Path] = {}
    for entry in search_paths:
        folder = Path(entry)
        try:
            children = sorted(folder.iterdir()) if folder.is_dir() else []
        except OSError:  # pragma: no cover - unreadable folder
            continue
        for child in children:
            stem, ext = _split_name(child.name)
            if not stem or ext.casefold() not in wanted:
                continue
            if _resolver_matches(stem, ext) or not child.is_file():
                continue
            found.setdefault(stem.upper(), child)
    return found


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def stage_copybook_aliases(
    search_paths: list[str],
    aliases: dict[str, str] | None = None,
    extensions: tuple[str, ...] = DEFAULT_COPYBOOK_EXTENSIONS,
) -> Path | None:
    """The staging directory holding `MEMBER.cpy` for every explicit alias
    and every automatic match in `search_paths`, or None when there is
    nothing to stage. Explicit aliases win over automatic matches."""
    members = automatic_aliases(search_paths, extensions)
    for member, file_name in (aliases or {}).items():
        members[member.upper()] = Path(file_name)
    if not members:
        return None

    digest = hashlib.sha256()
    for member in sorted(members):
        source = members[member]
        stat = source.stat()
        digest.update(
            f"{member}\0{source.resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode()
        )
    target = STAGING_ROOT / digest.hexdigest()[:16]
    sources = sorted({str(source.resolve()) for source in members.values()})
    if target.is_dir():
        _write_manifest(target, sources)
        return target

    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    # Built under a private name and renamed into place, so a concurrent
    # run never sees a half-filled directory.
    building = Path(tempfile.mkdtemp(prefix=".building-", dir=STAGING_ROOT))
    try:
        for member, source in members.items():
            _link_or_copy(source, building / f"{member}.cpy")
        try:
            building.rename(target)
        except OSError:
            # Another run staged the same set first; theirs is identical.
            if not target.is_dir():  # pragma: no cover - unexpected failure
                raise
    finally:
        if building.exists():
            shutil.rmtree(building, ignore_errors=True)
    _write_manifest(target, sources)
    return target


def _write_manifest(staged: Path, sources: list[str]) -> None:
    manifest = manifest_path(staged)
    if not manifest.is_file():
        manifest.write_text("".join(f"{source}\n" for source in sources))


def _is_under(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def staged_directories_for(roots: list[Path]) -> list[Path]:
    """The staging directories holding a copy of any file under one of
    `roots`, for `mockymock clean`. A directory whose manifest is missing
    or unreadable (staged before manifests existed) belongs to no one we
    can name, and is only a cache, so it is listed too; `.building-`
    directories of a run in progress never are."""
    if not STAGING_ROOT.is_dir():
        return []
    resolved = [root.resolve() for root in roots]
    found: list[Path] = []
    for staged in sorted(STAGING_ROOT.iterdir()):
        if staged.name.startswith(".") or not staged.is_dir():
            continue
        try:
            lines = manifest_path(staged).read_text().splitlines()
        except OSError:
            found.append(staged)
            continue
        if any(_is_under(Path(line), resolved) for line in lines if line):
            found.append(staged)
    return found
