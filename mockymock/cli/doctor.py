"""`mockymock doctor`: a terminal-native, one-shot readiness report.

Reuses `mockymock.runtime.status.probe()` verbatim -- the same read-only
Docker/GnuCOBOL probe `mockymock dashboard` already serves over HTTP --
and adds two more checks that probe has no reason to own: whether
`cobol-parser` is importable at all (and roughly current), and which
project config file (if any) this invocation would load. See
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
    from mockymock.cli.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as exc:
        return Check(
            id="config_file",
            label="config file",
            state=WARN,
            detail=str(exc),
        )
    if config.source is None:
        return Check(
            id="config_file",
            label="config file",
            state=OK,
            detail="none found (using built-in defaults)",
        )
    return Check(
        id="config_file",
        label="config file",
        state=OK,
        detail=str(config.source),
    )


def gather_full_status() -> DoctorReport:
    """The toolchain probe plus doctor's own two checks. Never raises for
    an unreachable daemon or missing cobol-parser -- those show up as
    `DOWN`/`WARN` checks, not exceptions; a `ConfigError` from a
    malformed config file is likewise downgraded to a `WARN` check here
    rather than propagated, since `doctor` itself must never crash on a
    broken environment -- that is exactly the case it exists to explain."""
    from mockymock.runtime.status import probe

    toolchain = probe()
    extra = (_check_cobol_parser(), _check_config_file())
    ready = toolchain.ready and all(c.state != DOWN for c in extra)
    return DoctorReport(toolchain=toolchain, extra_checks=extra, ready=ready)


_STATE_LABEL = {OK: "OK", WARN: "WARN", DOWN: "FAIL", UNKNOWN: "N/A"}

# Fix suggestions doctor knows how to append, keyed by check id. Anything
# not listed here (including every check.id status.py's probe() itself
# emits) has no fix line -- its own `detail` is expected to already
# explain what's wrong.
_FIX_SUGGESTIONS = {
    "cobol_parser": "Install it: pip install cobol-parser (or reinstall mocky-mock's own [dev]/[fast] extras)",
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
        lines.append("mockymock doctor: ready.")
    else:
        lines.append(
            "mockymock doctor: not ready -- fix the failing check(s) above, "
            "then re-run 'mockymock doctor' or 'mockymock setup'."
        )
    return "\n".join(lines)


def format_doctor_json(report: DoctorReport) -> dict[str, Any]:
    return report.to_dict()
