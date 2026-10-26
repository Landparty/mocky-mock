#!/usr/bin/env python3
"""Copy the `cobol-analysis` skill from a cobol-parser checkout.

cobol-parser owns the skill (.claude/skills/cobol-analysis/SKILL.md);
mockymock ships it unchanged as mockymock/cli/skills/cobol-analysis/ so
`mockymock skills install` and the cobol-testing plugin can hand it to a
COBOL tester. Never edit the copy here: change it in cobol-parser, then
run this script. tests/unit/test_cobol_analysis_skill_sync.py fails when
the two differ.

Usage: scripts/sync_cobol_analysis_skill.py [COBOL_PARSER_DIR]
(default: $COBOL_PARSER_REPO, else ../cobol-parser next to this repo).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RELATIVE = Path(".claude") / "skills" / "cobol-analysis"
DEST = REPO / "mockymock" / "cli" / "skills" / "cobol-analysis"


def canonical_dir(override: str | None = None) -> Path:
    root = override or os.environ.get("COBOL_PARSER_REPO")
    base = Path(root) if root else REPO.parent / "cobol-parser"
    return base / RELATIVE


def main(argv: list[str]) -> int:
    source = canonical_dir(argv[1] if len(argv) > 1 else None)
    if not (source / "SKILL.md").is_file():
        print(f"no cobol-analysis skill at {source}", file=sys.stderr)
        return 1
    shutil.rmtree(DEST, ignore_errors=True)
    shutil.copytree(source, DEST)
    print(f"copied {source} -> {DEST.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
