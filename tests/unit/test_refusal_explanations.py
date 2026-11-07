"""docs/2026-09-15-cut-editor-intelligence-design.md: REFUSAL_EXPLANATIONS
must cover every refusal code the codebase can actually emit -- a new
code added to a gate without a matching entry here is a real gap, not
something this test should let slide."""

import re
from pathlib import Path

from mockymock.analysis.refusal import REFUSAL_EXPLANATIONS

_MOCKYMOCK_ROOT = Path(__file__).resolve().parents[2] / "mockymock"

# Matches `code="SOME_CODE"` (a RefusalReason kwarg) and the literal
# string values of the _UNMOCKED_CODES / _UNSUPPORTED_SITE_CODES dicts in
# _types.py, which are the two ways a code enters this codebase without
# ever appearing as `code="..."` at its own construction site.
_CODE_KWARG_RE = re.compile(r'code="([A-Z_]+)"')
_QUOTED_CODE_RE = re.compile(r'"([A-Z]+(?:_[A-Z]+)+)"')
# The two other shapes a code is emitted in: flow_mocks.py's positional
# `_refusal("CODE", ...)` helper, and a problem string printed as
# `refused (CODE): ...` (checks.py's capture gate, export's column gate).
# Both used to slip past the scan, so `explain` called them uncatalogued.
_REFUSAL_HELPER_RE = re.compile(r'_refusal\(\s*"([A-Z]+(?:_[A-Z]+)+)"')
_REFUSED_TEXT_RE = re.compile(r"refused \(([A-Z]+(?:_[A-Z]+)+)\)")

# Not actual refusal codes, even though they match the all-caps pattern
# (label constants, dict keys that are prose not codes, etc.) -- explicit
# denylist so the scanner stays a strict superset check, not a guess.
_NOT_CODES = {
    "UNSUPPORTED_STATEMENT_LABEL",  # a dict KEY (the label), not a code
    "STOP_LITERAL",  # substring artifact, not a standalone code
}


def _codes_referenced_in(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    found = set(_CODE_KWARG_RE.findall(text))
    found |= set(_REFUSAL_HELPER_RE.findall(text))
    found |= set(_REFUSED_TEXT_RE.findall(text))
    if path.name in ("_types.py",):
        found |= set(_QUOTED_CODE_RE.findall(text))
    return found - _NOT_CODES


def test_every_refusal_code_in_the_codebase_is_catalogued():
    all_codes: set[str] = set()
    for path in _MOCKYMOCK_ROOT.rglob("*.py"):
        if "test" in path.parts:
            continue
        all_codes |= _codes_referenced_in(path)

    missing = sorted(all_codes - set(REFUSAL_EXPLANATIONS))
    assert not missing, (
        f"REFUSAL_EXPLANATIONS is missing an entry for: {missing}. "
        f"Add one in mockymock/analysis/refusal/_explanations.py."
    )


def test_every_catalogued_code_still_exists_in_the_codebase():
    """The reverse direction: a stale entry for a code nothing emits
    anymore is worth pruning, though not worth failing CI over --
    reported as a soft assertion message only via this test's own
    output if it ever fails, kept separate from the hard check above."""
    all_codes: set[str] = set()
    for path in _MOCKYMOCK_ROOT.rglob("*.py"):
        if "test" in path.parts:
            continue
        all_codes |= _codes_referenced_in(path)

    stale = sorted(set(REFUSAL_EXPLANATIONS) - all_codes)
    assert not stale, f"REFUSAL_EXPLANATIONS has stale entries: {stale}"


def test_every_explanation_is_a_real_sentence():
    for code, explanation in REFUSAL_EXPLANATIONS.items():
        assert len(explanation) > 40, f"{code}'s explanation looks too short"
        assert explanation.strip() == explanation, (
            f"{code}'s explanation has stray whitespace"
        )
