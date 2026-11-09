"""`mockymock doctor`: a terminal-native, one-shot readiness report.

Reuses `mockymock.runtime.status.probe()` verbatim -- the same read-only
Docker/GnuCOBOL probe `mockymock dashboard` already serves over HTTP --
and adds three more checks that probe has no reason to own: whether
`cobol-parser` is importable at all (and roughly current), which project
config file (if any) this invocation would load, and which AI assistant
mode that config puts the packaged skill in. See
docs/2026-09-15-doctor-command-design.md.

Never builds an image, starts a container, or otherwise mutates
anything -- `doctor` only ever suggests running `mockymock setup`,
never runs it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from mockymock.runtime.status import DOWN, OK, UNKNOWN, WARN, Check, ToolchainStatus

# Mirrors status.py's own severity ordering: OK < WARN < UNKNOWN < DOWN,
# worst last in the ranking below so a doctor report can sort worst-first.
_SEVERITY_RANK = {OK: 0, WARN: 1, UNKNOWN: 2, DOWN: 3}


@dataclass(frozen=True)
class DoctorReport:
    toolchain: ToolchainStatus
    extra_checks: tuple[Check, ...]
    ready: bool

    def all_checks(self) -> list[Check]:
        """Every check, worst-first (ties keep their original order)."""
        return sorted(
            (*self.toolchain.checks, *self.extra_checks),
            key=lambda c: -_SEVERITY_RANK.get(c.state, 0),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.toolchain.to_dict()
        payload["checks"] = [asdict(c) for c in self.all_checks()]
        payload["ready"] = self.ready
        return payload


def _check_cobol_parser() -> Check:
    try:
        import cobolparser
    except ImportError as exc:
        return Check(
            id="cobol_parser",
            label="cobol-parser",
            state=DOWN,
            detail=f"not importable: {exc}",
        )
    version = getattr(cobolparser, "__version__", None)
    if version is None:
        return Check(
            id="cobol_parser",
            label="cobol-parser",
            state=WARN,
            detail="importable, but has no __version__ attribute",
        )
    return Check(
        id="cobol_parser",
        label="cobol-parser",
        state=OK,
        detail=f"importable, {version}",
    )


def _check_config_file() -> Check:
    from mockymock.project.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as exc:
        # DOWN, not WARN (#389): run / lint / init all refuse a config
        # file that does not parse, and neither `setup` nor `run` fixes
        # it, so doctor must not call the environment ready.
        return Check(
            id="config_file",
            label="config file",
            state=DOWN,
            detail=str(exc),
        )
    if config.source is None:
        return Check(
            id="config_file",
            label="config file",
            state=OK,
            detail="none found (using built-in defaults)",
        )
    # Both files when a cobol.yml and a mockymock.toml are layered, in the
    # order they apply -- reporting only the winner would leave the other
    # invisible, which is the question this check exists to answer.
    return Check(
        id="config_file",
        label="config file",
        state=OK,
        detail=", then ".join(str(path) for path in config.sources)
        or str(config.source),
    )


def _check_ai_mode() -> Check:
    """Which AI assistant mode the packaged skill is operating under here
    (`mockymock/project/ai_mode.py`). Always `OK` -- every mode is a valid
    way to work, so this reports, it doesn't judge, and `ready` is never
    affected by it. It earns its line because `doctor` is the first
    command the skill runs against a new program: the mode is a property
    of the project an assistant has to know, and this is where project
    properties already get printed.

    Loads the config a second time rather than sharing
    `_check_config_file`'s: that function's signature is called directly
    by its own tests, and a one-shot command re-reading one small TOML
    file is cheaper than the coupling.
    """
    from mockymock.project.ai_mode import DEFAULT_MODE, resolve_mode
    from mockymock.project.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError:
        # The config-file check above already reports the parse error
        # itself; here it only means the mode can't be read, and a
        # mode-less assistant falls back to the default.
        return Check(
            id="ai_mode",
            label="AI assistant mode",
            state=OK,
            detail=f"{DEFAULT_MODE} (fallback -- the config file above could not be read)",
        )
    resolved = resolve_mode(config)
    origin = "built-in default" if resolved.source is None else str(resolved.source)
    return Check(
        id="ai_mode",
        label="AI assistant mode",
        state=OK,
        detail=f"{resolved.mode} -- {resolved.contract.summary} ({origin})",
    )


def gather_full_status() -> DoctorReport:
    """The toolchain probe plus doctor's own three checks. Never raises for
    an unreachable daemon or missing cobol-parser -- those show up as
    `DOWN`/`WARN` checks, not exceptions; a `ConfigError` from a
    malformed config file is likewise turned into a `DOWN` check here
    rather than propagated, since `doctor` itself must never crash on a
    broken environment -- that is exactly the case it exists to explain."""
    from mockymock.runtime.status import probe

    toolchain = probe()
    extra = (_check_cobol_parser(), _check_config_file(), _check_ai_mode())
    # Ready means nothing is DOWN. A WARN (a stopped container, a stale
    # image) is something `mockymock setup` or
    # the next `run` sorts out on its own, not a failure the user must
    # fix first -- see docs/2026-09-15-doctor-command-design.md, "Exit
    # code": WARN -> 0. `probe()`'s own `ready` is stricter (it also
    # drops on a stopped container), so it is not reused here.
    ready = all(c.state != DOWN for c in (*toolchain.checks, *extra))
    return DoctorReport(toolchain=toolchain, extra_checks=extra, ready=ready)


_STATE_LABEL = {OK: "OK", WARN: "WARN", DOWN: "FAIL", UNKNOWN: "N/A"}

# Fix suggestions doctor knows how to append, keyed by check id. Anything
# not listed here (including every check.id status.py's probe() itself
# emits) has no fix line -- its own `detail` is expected to already
# explain what's wrong.
_FIX_SUGGESTIONS = {
    "cobol_parser": "Install it: pip install cobol-parser (or reinstall mocky-mock's own [dev]/[fast] extras)",
    "config_file": "Fix the config file: run, lint and init refuse to start until it parses",
}


def format_doctor_text(report: DoctorReport) -> str:
    lines = []
    for check in report.all_checks():
        label = _STATE_LABEL.get(check.state, check.state.upper())
        lines.append(f"[{label:>4}] {check.label:<20} {check.detail}")
        if check.state != OK:
            fix = _FIX_SUGGESTIONS.get(check.id)
            if fix:
                lines.append(f"       -> {fix}")
    lines.append("")
    if report.ready:
        if any(c.state != OK for c in report.all_checks()):
            lines.append(
                "mockymock doctor: ready (with warnings -- see the [WARN] "
                "check(s) above)."
            )
        else:
            lines.append("mockymock doctor: ready.")
    else:
        lines.append(
            "mockymock doctor: not ready -- fix the [FAIL] check(s) above, "
            "then re-run 'mockymock doctor' or 'mockymock setup'."
        )
    return "\n".join(lines)


def format_doctor_json(report: DoctorReport) -> dict[str, Any]:
    return report.to_dict()
