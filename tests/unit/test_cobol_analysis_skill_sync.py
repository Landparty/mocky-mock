"""mockymock/cli/skills/cobol-analysis/ is cobol-parser's skill, shipped
unchanged: there is one source of it, in cobol-parser. A hand edit here
drifts from it (the old curated copy had already lost cobol-parser's MCP
paragraph), so compare the two whenever a cobol-parser checkout sits next
to this one ($COBOL_PARSER_REPO or ../cobol-parser)."""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "sync_cobol_analysis_skill", REPO / "scripts" / "sync_cobol_analysis_skill.py"
)
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_shipped_copy_matches_cobol_parser():
    source = sync.canonical_dir()
    if not (source / "SKILL.md").is_file():
        pytest.skip(f"no cobol-parser checkout at {source.parents[2]}")
    assert _files(sync.DEST) == _files(source), (
        "mockymock's cobol-analysis skill differs from cobol-parser's; edit it "
        "there, then run scripts/sync_cobol_analysis_skill.py"
    )


def test_shipped_copy_names_its_source():
    text = (sync.DEST / "SKILL.md").read_text("utf-8")
    assert "this file is the one source of the `cobol-analysis`" in text
    assert "mockymock analyze <subcommand>" in text
