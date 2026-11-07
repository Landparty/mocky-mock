"""Shared helper for unit tests that scaffold a `.cut` with
`mockymock generate --with-data` (moved out of the former
test_bug_hunt_m1_fixes.py, 2026-11-07)."""

from __future__ import annotations


def _generate(tmp_path, name: str, cbl: str, *extra: str) -> str:
    from mockymock.cli.main import main

    source = tmp_path / f"{name}.cbl"
    source.write_text(cbl)
    out = tmp_path / f"{name}.cut"
    assert main(["generate", str(source), "--with-data", "-o", str(out), *extra]) == 0
    return out.read_text()
