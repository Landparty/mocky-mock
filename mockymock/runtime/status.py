"""Read-only health probe of the Docker toolchain.

This is the data source behind `mockymock dashboard` (see
`mockymock/web/`). Every check maps 1:1 onto a step of `ensure_toolchain`'s
lifecycle table in `.okf/runtime.md`, but **nothing here mutates anything**:
`ensure_toolchain()` builds images, `docker rm -f`s stale containers, and
creates containers, so a page polling it every few seconds would trigger
image rebuilds. The probe only reports what `ensure_toolchain` *would*
find, using `docker info` / `docker image inspect` / `docker inspect`,
all of which are pure reads.

Timeouts are deliberately much shorter than the toolchain's own 600s
default -- a dashboard poll that hangs for ten minutes is worse than one
that reports "unreachable".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from mockymock.runtime import docker_toolchain
from mockymock.runtime.docker_toolchain import DockerNotAvailableError

# A dashboard poll must fail fast rather than hang on a wedged daemon.
PROBE_TIMEOUT = 15

# Check states, in worsening order. `warn` means "usable-ish but not what
# `mockymock run` needs"; `down` means the step would fail outright;
# `unknown` means an earlier step failed so this one was never reached.
OK = "ok"
WARN = "warn"
DOWN = "down"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Check:
    """One lifecycle step's observed state."""

    id: str
    label: str
    state: str
    detail: str


@dataclass(frozen=True)
class ToolchainStatus:
    ready: bool
    checked_at: str
    image: str
    container: str
    cobc_version: str | None
    checks: tuple[Check, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON payload for the dashboard. Kept explicit (rather than
        `asdict(self)`) because this shape is a wire contract the page
        depends on -- new fields are additive, existing ones don't move."""
        return {
            "ready": self.ready,
            "checked_at": self.checked_at,
            "image": self.image,
            "container": self.container,
            "cobc_version": self.cobc_version,
            "checks": [asdict(check) for check in self.checks],
        }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _probe_daemon() -> Check:
    label = "Docker daemon"
    try:
        info = docker_toolchain._docker("info", timeout=PROBE_TIMEOUT)
    except DockerNotAvailableError as exc:
        # Docker CLI absent, or `docker info` itself hung past the timeout.
        return Check("daemon", label, DOWN, str(exc))
    if info.returncode != 0:
        detail = info.stderr.strip().splitlines()
        return Check(
            "daemon",
            label,
            DOWN,
            detail[-1] if detail else "docker info exited non-zero",
        )
    return Check("daemon", label, OK, "reachable")


def _probe_image() -> Check:
    label = "Toolchain image"
    try:
        result = docker_toolchain._docker(
            "image", "inspect", docker_toolchain.IMAGE, timeout=PROBE_TIMEOUT
        )
    except DockerNotAvailableError as exc:
        return Check("image", label, DOWN, str(exc))
    if result.returncode != 0:
        return Check(
            "image",
            label,
            DOWN,
            f"{docker_toolchain.IMAGE} is not built - run `mockymock setup`",
        )
    return Check("image", label, OK, f"{docker_toolchain.IMAGE} present")


def _probe_container() -> tuple[Check, bool]:
    """Returns the container check plus whether it is running *and* built
    from the current image -- i.e. whether it is safe to `docker exec` into
    for the cobc probe below."""
    label = "Toolchain container"
    name = docker_toolchain.CONTAINER
    try:
        found = docker_toolchain._inspect_container()
    except DockerNotAvailableError as exc:
        return Check("container", label, DOWN, str(exc)), False
    if found is None:
        return (
            Check(
                "container",
                label,
                DOWN,
                f"{name} does not exist - run `mockymock setup`",
            ),
            False,
        )
    running, image = found
    if image != docker_toolchain.IMAGE:
        # Same drift `ensure_toolchain` step 3 rm+recreates on: the
        # Dockerfile changed since this container was created, so it is
        # running a stale toolchain.
        return (
            Check(
                "container",
                label,
                WARN,
                f"{name} was created from {image} (expected "
                f"{docker_toolchain.IMAGE}) - `mockymock setup` will recreate it",
            ),
            False,
        )
    if not running:
        return (
            Check("container", label, WARN, f"{name} exists but is stopped"),
            False,
        )
    return Check("container", label, OK, f"{name} running"), True


def _probe_cobc(container_usable: bool) -> tuple[Check, str | None]:
    label = "GnuCOBOL compiler"
    if not container_usable:
        return Check("cobc", label, UNKNOWN, "container not running"), None
    try:
        version = docker_toolchain.cobc_version()
    except DockerNotAvailableError as exc:
        # Container is up but cobc is broken inside the image.
        return Check("cobc", label, DOWN, str(exc)), None
    return Check("cobc", label, OK, version), version


def probe() -> ToolchainStatus:
    """Probe the toolchain without touching it. Later checks short-circuit
    to `unknown` once an earlier one fails, mirroring the order
    `ensure_toolchain` works through them -- reporting "container missing"
    when the daemon is simply down would be noise, not information."""
    daemon = _probe_daemon()
    if daemon.state != OK:
        checks = (
            daemon,
            Check("image", "Toolchain image", UNKNOWN, "daemon unreachable"),
            Check("container", "Toolchain container", UNKNOWN, "daemon unreachable"),
            Check("cobc", "GnuCOBOL compiler", UNKNOWN, "daemon unreachable"),
        )
        return ToolchainStatus(
            ready=False,
            checked_at=_now(),
            image=docker_toolchain.IMAGE,
            container=docker_toolchain.CONTAINER,
            cobc_version=None,
            checks=checks,
        )

    image = _probe_image()
    container, container_usable = _probe_container()
    cobc, version = _probe_cobc(container_usable)
    checks = (daemon, image, container, cobc)
    return ToolchainStatus(
        ready=all(check.state == OK for check in checks),
        checked_at=_now(),
        image=docker_toolchain.IMAGE,
        container=docker_toolchain.CONTAINER,
        cobc_version=version,
        checks=checks,
    )
