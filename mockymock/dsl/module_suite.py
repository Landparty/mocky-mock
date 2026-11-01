"""`generate --real`: turn a scaffolded unit suite into a load-module suite.

`generate` scaffolds the entry program as always; this rewrites its text so
the named subprograms run for real (docs/2026-11-01-real-call-integration-
design.md):

* every `MOCK CALL "X"` block of a real program X is dropped, together
  with the lines naming the CAPTURE targets that block declared (they no
  longer exist), and one `USE REAL CALL "X" FROM "<path>"` goes into a
  BEFORE-EACH block instead. `VERIFY CALL "X"` lines stay: a real call is
  still counted.
* every boundary of each real program gets the same placeholder MOCK a
  bundle-less scaffold would write for it (`directive_snippet`), in that
  BEFORE-EACH block, so the suite passes the real-program gate as written;
  a CALL from one real program to another becomes a USE REAL CALL too.

The placeholders answer every case alike; a case that needs other values
overrides one with its own MOCK of the same key (a TESTCASE's mock wins
over BEFORE-EACH's).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from mockymock.analysis.real_programs import PreparedReal
from mockymock.dsl.model import MockCategory

_MOCK_CALL_RE = re.compile(r'^MOCK\s+(?:CALL|MQ)\s+"(?P<key>[^"]*)"(?:\s+ROWS)?$')
_CAPTURE_RE = re.compile(
    r"^CAPTURE\s+ARG\s+\d+\s+INTO\s+(?P<target>\S+)$", re.IGNORECASE
)
_END_MOCK_RE = re.compile(r"^END-MOCK\.?$", re.IGNORECASE)
_TESTSUITE_RE = re.compile(r"^TESTSUITE\b")


@dataclass
class RealLink:
    """One program `generate --real` links in."""

    prepared: PreparedReal

    @property
    def key(self) -> str:
        return self.prepared.program_id.upper()


def link_real_programs(
    cut_text: str, links: list[RealLink], cut_path: Path
) -> tuple[str, list[str]]:
    """(rewritten `.cut` text, notes for the user)."""
    from mockymock.dsl.generator import directive_snippet

    real_keys = {link.key for link in links}
    lines = cut_text.split("\n")
    kept: list[str] = []
    dropped_targets: set[str] = set()
    dropped_blocks = 0
    skipping = False
    for line in lines:
        stripped = line.strip()
        if skipping:
            capture = _CAPTURE_RE.match(stripped)
            if capture is not None:
                dropped_targets.add(capture.group("target").upper())
            if _END_MOCK_RE.match(stripped):
                skipping = False
            continue
        match = _MOCK_CALL_RE.match(stripped)
        if match is not None and match.group("key").upper() in real_keys:
            skipping = True
            dropped_blocks += 1
            continue
        kept.append(line)
    if dropped_targets:
        kept = [
            line
            for line in kept
            if not any(
                re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", line.upper())
                for t in dropped_targets
            )
        ]

    block: list[str] = []
    seen_headers: set[str] = set()
    for link in links:
        source = Path(link.prepared.spec.source)
        relative = Path(os.path.relpath(source, cut_path.parent)).as_posix()
        block.append(f'    USE REAL CALL "{link.key}" FROM "{relative}"')
    for link in links:
        prepared = link.prepared
        for site in prepared.surface.boundary_sites:
            if site.category is None:
                continue
            if site.category is MockCategory.CALL and any(
                key.upper() in real_keys for key in site.keys
            ):
                continue
            snippet = directive_snippet(
                site, prepared.surface, prepared.file_status_fields
            )
            if snippet is None:
                continue
            header = snippet.splitlines()[0].strip()
            if header in seen_headers:
                continue
            seen_headers.add(header)
            block.append(f"    *> {link.key} line {site.line} ({site.paragraph_name})")
            block.extend(snippet.splitlines())

    out: list[str] = []
    inserted = False
    for line in kept:
        out.append(line)
        if not inserted and line.strip() == "BEFORE-EACH":
            out.extend(block)
            inserted = True
    if not inserted:
        out = []
        for line in kept:
            out.append(line)
            if not inserted and _TESTSUITE_RE.match(line.strip()):
                out.extend(["", "BEFORE-EACH", *block, "END-BEFORE"])
                inserted = True
    notes = [
        f"linked {len(links)} real program(s): "
        + ", ".join(link.key for link in links)
        + f" -- {dropped_blocks} MOCK CALL block(s) replaced by USE REAL CALL; "
        f"their boundaries are placeholder mocks in BEFORE-EACH, edit them "
        f"(or override one per TESTCASE) to give each case its data"
    ]
    return "\n".join(out), notes
