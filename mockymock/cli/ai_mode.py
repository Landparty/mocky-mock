"""AI assistant modes: how much the packaged Claude Code skill checks in
with the developer while it builds a `.cut` suite.

The skill (`mockymock/cli/skills/mockymock/`) prescribes *what* an
assistant does -- paragraph pass, then whole-program pass. This module
owns the orthogonal axis: *how closely the developer is watching while it
happens*. Three modes, from most to least developer involvement:
`hands-on` (propose, wait for a yes), `guided` (the default -- narrate
every step, stop at the checkpoints), `hands-off` (run the whole workflow
and report once at the end).

A mode changes how often the assistant stops to ask. It never changes
what the assistant is allowed to destroy: `ALWAYS_ASK` is the floor, and
it holds in `hands-off` exactly as it does in `hands-on`. See
docs/2026-09-16-ai-assistant-modes-design.md.

The mode lives in the project config file (`ai_mode` in `mockymock.toml`
or `pyproject.toml`'s `[tool.mockymock]`), so it is per-repo and survives
across sessions -- a team that wants the assistant to check in on every
change commits that, and every session honors it without being told
again. `mockymock skills mode` reads it back (and `--set` writes it);
`mockymock doctor` reports it alongside the config file it came from.

This module is stdlib-only and imports nothing from the rest of
mockymock at runtime -- `cli/config.py` imports `MODES`/`DEFAULT_MODE`
from here to validate the key, so the dependency may not point the other
way.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, see module docstring
    from mockymock.cli.config import MockymockConfig

CONFIG_KEY = "ai_mode"

# The section of the universal `cobol.yml` that carries this tool's keys.
# Declared here rather than in cli/config.py because that module already
# imports from this one -- see the module docstring on the import direction.
_UNIVERSAL_SECTION = "mockymock"

HANDS_ON = "hands-on"
GUIDED = "guided"
HANDS_OFF = "hands-off"

# Ordered most-supervised first; `mockymock skills mode` prints them in
# this order, so it reads as a dial rather than an unordered set.
MODES = (HANDS_ON, GUIDED, HANDS_OFF)

# `guided` is what the skill described before modes existed, so an
# existing project with no `ai_mode` key keeps exactly the behavior it
# had.
DEFAULT_MODE = GUIDED


@dataclass(frozen=True)
class ModeContract:
    """What one mode actually changes about the assistant's behavior.

    Four separate fields rather than one prose blob because each is
    consumed on its own: `summary` in `doctor`'s one-line detail and the
    mode list, the other three as the body of `mockymock skills mode`
    and of `reference/modes.md`'s table.
    """

    name: str
    summary: str
    narration: str
    decides: str
    asks: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "summary": self.summary,
            "narration": self.narration,
            "decides": self.decides,
            "asks": self.asks,
        }


CONTRACTS: dict[str, ModeContract] = {
    HANDS_ON: ModeContract(
        name=HANDS_ON,
        summary="propose first, wait for a yes before each change",
        narration=(
            "Before every command and every edit: say what it is, on which "
            "paragraph, and what you expect. Then wait. Read-only commands "
            "(analyze, fixtures, collect, lint, explain, doctor) may be run "
            "without asking -- they change nothing."
        ),
        decides=(
            "Nothing that writes a file or runs a program. Show the MOCK "
            "block, the EXPECT, the command line -- the developer applies "
            "or approves it."
        ),
        asks=(
            "Every .cut edit, every run, and the choice of which paragraph "
            "to take next."
        ),
    ),
    GUIDED: ModeContract(
        name=GUIDED,
        summary="narrate every step, stop at the checkpoints",
        narration=(
            "One sentence before each command, the result in plain language "
            "after it, then where things stand (n of m paragraphs green) at "
            "the end of each loop iteration."
        ),
        decides=(
            "Mock bodies, EXPECT/VERIFY lines, and which paragraph is next, "
            "within the paragraph pass -- announced, not asked."
        ),
        asks=(
            "Overwriting a .cut that has hand-written cases, choosing a "
            "--scenarios mode, moving from the paragraph pass to the "
            "whole-program pass, and parking a failing paragraph."
        ),
    ),
    HANDS_OFF: ModeContract(
        name=HANDS_OFF,
        summary="run the whole workflow, report once at the end",
        narration=(
            "One report at the end: every paragraph with its verdict, the "
            "decisions you took alone and why, what is parked, and what is "
            "still open. No running commentary -- nobody is reading it."
        ),
        decides=(
            "The whole loop end to end: scaffold, paragraph pass, "
            "whole-program pass, coverage and mutation. Pick the "
            "--scenarios mode from the program's own scenario_coverage and "
            "say which you picked and why."
        ),
        asks=(
            "Nothing but the floor below. A paragraph that will not go "
            "green gets parked in writing and the run continues -- do not "
            "stall waiting for an answer nobody is there to give."
        ),
    ),
}

# The floor. These hold in every mode, `hands-off` included: a mode says
# how often the assistant checks in, never what it may destroy or
# quietly decide. Each one is irreversible, outside the suite, or a
# judgement about the program rather than the test -- the three things a
# delegated run must not settle on its own.
ALWAYS_ASK = (
    "Editing the .cbl program under test. The suite is the deliverable; "
    "the program is the developer's.",
    "Overwriting a .cut containing cases you did not write this session -- "
    "plain `generate` overwrites its output path silently. Use `generate "
    "--fill <cut>` or `-o <new file>`.",
    "Turning a suspected program bug into a passing assertion. Report the "
    "expected and actual values and leave it open, in every mode -- "
    "hands-off means you do not stop, not that you guess.",
    "Anything outside the mockymock loop on the developer's behalf: git "
    "commits, pushes, deleting files, installing tooling.",
)


@dataclass(frozen=True)
class ResolvedMode:
    """The active mode plus where it came from -- the provenance matters
    as much as the value, since a mode set in a parent directory's
    config file is easy to be surprised by."""

    mode: str
    source: Path | None

    @property
    def contract(self) -> ModeContract:
        return CONTRACTS[self.mode]

    @property
    def origin(self) -> str:
        if self.source is None:
            return f"built-in default -- no {CONFIG_KEY} in any config file"
        return str(self.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "source": None if self.source is None else str(self.source),
            "origin": self.origin,
        }


class ModeError(Exception):
    """A mode value that isn't one of `MODES`, or a mode that cannot be
    written to the config file that's in effect. Same fail-closed
    posture as the rest of the CLI: named, actionable, never silently
    coerced to the default."""


def validate(mode: str) -> str:
    """Return `mode` unchanged if it is a known mode, else raise."""
    if mode not in CONTRACTS:
        raise ModeError(
            f"unknown AI mode {mode!r} (expected one of: {', '.join(MODES)})"
        )
    return mode


def resolve_mode(config: MockymockConfig | None) -> ResolvedMode:
    """The active mode for this project. `config=None` (no config loaded,
    or one that failed to parse) resolves to the built-in default rather
    than raising -- the caller that cares about a malformed config file
    reports that itself."""
    if config is None or config.ai_mode is None:
        return ResolvedMode(mode=DEFAULT_MODE, source=None)
    # The file that actually set `ai_mode`, not merely the last-loaded
    # one (see MockymockConfig.ai_mode_source); a config built by hand
    # without it falls back to `source` as before.
    source = getattr(config, "ai_mode_source", None) or config.source
    return ResolvedMode(mode=validate(config.ai_mode), source=source)


def _assignment_line(mode: str) -> str:
    return f'{CONFIG_KEY} = "{mode}"\n'


def _rewrite_mockymock_toml(path: Path, mode: str) -> None:
    """Replace an existing top-level `ai_mode = ...` line, or append one.

    Line-based on purpose: it preserves comments, key order, and
    formatting, which a tomllib-read/round-trip-write cannot (tomllib is
    read-only, and mockymock takes no TOML-writing dependency for one
    key). Safe here because `mockymock.toml`'s schema is a flat table --
    `config.py` rejects every key it doesn't know, so a `[table]` header
    the scan could be fooled by is already a ConfigError.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModeError(f"could not read {path}: {exc}") from exc
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(CONFIG_KEY) and "=" in stripped:
            if stripped.split("=", 1)[0].strip() == CONFIG_KEY:
                lines[index] = _assignment_line(mode)
                break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(_assignment_line(mode))
    try:
        path.write_text("".join(lines), encoding="utf-8")
    except OSError as exc:
        raise ModeError(f"could not write {path}: {exc}") from exc


def write_mode(
    mode: str, config: MockymockConfig | None, *, start_dir: Path | None = None
) -> Path:
    """Persist `mode` and return the file written.

    Three cases: an existing `mockymock.toml` is edited in place; no
    config file at all means a new `mockymock.toml` in `start_dir`
    (default: cwd); a config that lives in a `pyproject.toml` or in the
    universal `cobol.yml` is a **refusal**, not a silent redirect.

    For `pyproject.toml`, writing a `mockymock.toml` beside it would not
    merge with it -- `find_tool_config` is first-match-wins per directory
    and `mockymock.toml` wins, so the new file would shadow that project's
    `copybook_path`/`seed`/`test_root` wholesale. For `cobol.yml`, a new
    `mockymock.toml` *would* layer over it correctly, but silently splitting
    a project's settings across two files when the point of the universal
    one is to have a single place is not a decision to make on the user's
    behalf. Naming the lines to paste is the non-destructive answer to both.
    """
    validate(mode)
    source = None if config is None else config.source
    if source is not None and source.name in ("cobol.yml", "cobol.yaml"):
        raise ModeError(
            f"{source} is the universal project config, which mockymock "
            f"reads but does not rewrite. Add this under its "
            f"'{_UNIVERSAL_SECTION}:' section instead:\n"
            f"    {_UNIVERSAL_SECTION}:\n"
            f"      {CONFIG_KEY}: {mode}"
        )
    if source is not None and source.name != "mockymock.toml":
        raise ModeError(
            f"{source} configures mockymock via [tool.mockymock], and "
            f"writing a mockymock.toml next to it would shadow that whole "
            f"table. Add this line to [tool.mockymock] in {source} "
            f"instead:\n    {_assignment_line(mode).rstrip()}"
        )
    if source is not None:
        _rewrite_mockymock_toml(source, mode)
        return source
    target = (start_dir or Path.cwd()) / "mockymock.toml"
    if target.exists():
        # Only reachable when the file exists but load_config didn't
        # return it (an unreadable file, or a walk that started
        # elsewhere) -- edit it rather than clobbering it.
        _rewrite_mockymock_toml(target, mode)
        return target
    try:
        target.write_text(_assignment_line(mode), encoding="utf-8")
    except OSError as exc:
        raise ModeError(f"could not write {target}: {exc}") from exc
    return target


# Wrapped rather than emitted as one long line per field: this report is
# read in a terminal, and `doctor`'s one-line-per-check layout doesn't
# carry over to three sentences of contract text.
_WRAP_WIDTH = 76


def _wrap(text: str, label: str = "", indent: str = "  ") -> list[str]:
    prefix = f"{indent}{label}"
    return textwrap.wrap(
        text,
        width=_WRAP_WIDTH,
        initial_indent=prefix,
        subsequent_indent=" " * len(prefix),
    )


def format_mode_report(resolved: ResolvedMode) -> str:
    """The human-readable body of `mockymock skills mode`: the dial with
    the active notch marked, the active mode's contract in full, the
    floor, and how to change it. One screen -- an assistant reads this
    at the start of a session and a developer reads it to find out what
    they've delegated."""
    lines = [
        f"mockymock skills mode: {resolved.mode}  ({resolved.origin})",
        "",
    ]
    width = max(len(name) for name in MODES)
    for name in MODES:
        marker = "->" if name == resolved.mode else "  "
        lines.append(f"  {marker} {name:<{width}}  {CONTRACTS[name].summary}")
    contract = resolved.contract
    lines += [
        "",
        f"In {contract.name}:",
    ]
    lines += _wrap(contract.narration, "narrates: ")
    lines += _wrap(contract.decides, "decides:  ")
    lines += _wrap(contract.asks, "asks:     ")
    lines += ["", "Always asked, in every mode:"]
    for item in ALWAYS_ASK:
        lines += _wrap(item, "- ")
    lines += [
        "",
        f"Change it: mockymock skills mode --set <{'|'.join(MODES)}>",
        f'           (or {CONFIG_KEY} = "<mode>" in mockymock.toml, which is '
        f"what --set writes)",
    ]
    return "\n".join(lines)


def format_mode_json(resolved: ResolvedMode) -> dict[str, Any]:
    """`--json` for an assistant or the VS Code extension: the active
    mode *and* every mode's contract, so a caller can render the dial
    without hard-coding a copy of it that drifts."""
    return {
        "version": 1,
        **resolved.to_dict(),
        "default": DEFAULT_MODE,
        "config_key": CONFIG_KEY,
        "modes": [CONTRACTS[name].to_dict() for name in MODES],
        "always_ask": list(ALWAYS_ASK),
    }
