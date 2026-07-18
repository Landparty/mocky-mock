"""Docker-backed GnuCOBOL toolchain.

mockymock is Docker-only by design (decision 2026-07-04): compilation and
execution both happen inside a persistent `mockymock-cobc` container so
that a correctly configured cobc is guaranteed (no COB_CONFIG_DIR issues)
and compiled binaries never execute on the host (no Windows Smart App
Control / WDAC interference). If the daemon is unreachable we fail loudly;
there is no local-cobc fallback.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mockymock.runtime.compiler import CompileResult
from mockymock.runtime.executor import (
    NOT_FOUND_EXIT_CODE,
    TIMEOUT_EXIT_CODE,
    ExecutionResult,
    _coerce_output,
)

# Bundled under the package itself (not the repo-root docker/) so it ships
# inside the wheel and is found under any install mode -- editable sibling
# checkout or a real `uv tool install` with no repo present at all.
_DOCKER_CONTEXT = Path(__file__).resolve().parent / "docker"


def _image_tag(dockerfile_text: str | None = None) -> str:
    """8-char content hash of docker/Dockerfile, used as the image tag so
    that editing the Dockerfile changes the tag, `docker image inspect`
    misses, and `ensure_toolchain` rebuilds instead of silently reusing a
    stale image."""
    if dockerfile_text is None:
        dockerfile_text = (_DOCKER_CONTEXT / "Dockerfile").read_text()
    return hashlib.sha256(dockerfile_text.encode()).hexdigest()[:8]


IMAGE = f"mockymock-gnucobol:{_image_tag()}"
CONTAINER = "mockymock-cobc"
WORK_ROOT = Path.home() / ".mockymock" / "work"

# Container hardening (2026-07-07 audit finding 4.3). The container compiles
# and *runs untrusted COBOL*: a hostile `.cbl` -- or a MOCK body, which the
# splicer injects verbatim -- can `CALL "SYSTEM"` and run arbitrary shell
# inside the container. There is no host escape, but an unhardened container
# lets that shell exfiltrate over the network, fork-bomb, or exhaust memory,
# and tamper with other concurrent runs' sandboxes under the shared /work
# mount. These `docker run` flags defang it with controls that are portable
# across the Linux and Windows Docker Desktop hosts mockymock targets:
#
#   --network none                    no outbound network -> no exfiltration
#   --pids-limit <n>                  fork-bomb ceiling
#   --memory / --memory-swap <limit>  memory ceiling; swap pinned to the same
#                                     value so the limit actually bites
#   --cap-drop ALL + --cap-add DAC_OVERRIDE  drop every Linux capability except
#                                     the one root needs for the bind mount
#   --security-opt no-new-privileges  setuid binaries cannot escalate
#
# The container still runs as root: the bind-mounted work root is owned by the
# host user, whose uid is not portable across machines and is absent on
# Windows, so a fixed non-root uid would break cobc's write of the compiled
# binary into /work. Root is *neutralized* by the controls above (network,
# pids, memory, capabilities, privilege escalation) rather than dropped. See
# `.okf/runtime.md` (Threat model) for the full rationale and residual risk.
#
# Why DAC_OVERRIDE is added back: sandboxes are created host-side by
# `tempfile.mkdtemp` (mode 0700, owned by the host uid) and bind-mounted in.
# Container-root reads the .cbl and writes the compiled binary through that
# mount purely via CAP_DAC_OVERRIDE -- the capability that lets root bypass
# file permission bits -- so `--cap-drop ALL` alone makes cobc fail with
# "Permission denied" on host-owned files. DAC_OVERRIDE only bypasses DAC
# checks on the already-isolated /work mount; the caps that matter for
# container escape (SYS_ADMIN, NET_RAW, SETUID/SETGID, MKNOD, ...) stay dropped.
PIDS_LIMIT = 512
MEMORY_LIMIT = "1g"

_HARDENING_FLAGS: tuple[str, ...] = (
    "--network",
    "none",
    "--pids-limit",
    str(PIDS_LIMIT),
    "--memory",
    MEMORY_LIMIT,
    "--memory-swap",
    MEMORY_LIMIT,
    "--cap-drop",
    "ALL",
    "--cap-add",
    "DAC_OVERRIDE",
    "--security-opt",
    "no-new-privileges",
)


class DockerNotAvailableError(RuntimeError):
    """Raised when the Docker daemon (or CLI) cannot be reached or the
    toolchain image/container cannot be brought up."""


def to_container_path(host_path: Path, work_root: Path = WORK_ROOT) -> str:
    """Map a host path under `work_root` to its /work path inside the
    container. The bind mount is `work_root -> /work`, established once at
    container creation, so only paths under the work root are visible to
    `docker exec`."""
    try:
        rel = host_path.resolve().relative_to(work_root.resolve())
    except ValueError:
        raise ValueError(
            f"{host_path} is not under the Docker work root {work_root}; "
            f"only files inside the work root are visible to the container"
        ) from None
    return "/work/" + rel.as_posix()


_DAEMON_HINT = (
    "Docker is required: mockymock compiles and runs COBOL inside a "
    "GnuCOBOL container. Start Docker Desktop (or the docker service) "
    "and re-run."
)


def _docker(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a docker CLI command, translating a missing/broken CLI into
    DockerNotAvailableError."""
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DockerNotAvailableError(f"{_DAEMON_HINT} ({exc})") from exc


# One docker inspect yields both facts ensure_toolchain needs about the
# container: whether it is running, and which image it was created from.
_CONTAINER_INSPECT_FORMAT = "{{.State.Running}} {{.Config.Image}}"


def _inspect_container() -> tuple[bool, str] | None:
    """Return (running, image) for the toolchain container, or None if no
    container with that name exists."""
    state = _docker("inspect", "-f", _CONTAINER_INSPECT_FORMAT, CONTAINER, timeout=30)
    if state.returncode != 0:
        return None
    running, _, image = state.stdout.strip().partition(" ")
    return running == "true", image


def _start_container() -> None:
    start = _docker("start", CONTAINER, timeout=60)
    if start.returncode != 0:
        raise DockerNotAvailableError(
            f"failed to start container {CONTAINER}:\n{start.stderr.strip()}"
        )


def _create_container() -> None:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    run = _docker(
        "run",
        "-d",
        "--name",
        CONTAINER,
        *_HARDENING_FLAGS,
        "-v",
        f"{WORK_ROOT.as_posix()}:/work",
        IMAGE,
        "sleep",
        "infinity",
    )
    if run.returncode != 0:
        # Concurrent first invocations race on `docker run --name`: the
        # loser gets "name already in use" even though the winner's
        # container is perfectly usable. Re-check instead of failing.
        if "already in use" in run.stderr:
            found = _inspect_container()
            if found is not None:
                running, _image = found
                if running:
                    return
                _start_container()
                return
        raise DockerNotAvailableError(
            f"failed to start container {CONTAINER}:\n{run.stderr.strip()}"
        )


def ensure_toolchain() -> None:
    """Bring the toolchain up: daemon reachable, image built, container
    running *and created from the current image*. Idempotent; called by
    both `mockymock setup` and every `mockymock run` (so the container is
    restarted if it died, and recreated if docker/Dockerfile changed --
    the content-hash tag in IMAGE only helps if a stale container is not
    silently reused)."""
    info = _docker("info", timeout=30)
    if info.returncode != 0:
        raise DockerNotAvailableError(f"{_DAEMON_HINT}\n{info.stderr.strip()}")

    image = _docker("image", "inspect", IMAGE, timeout=30)
    if image.returncode != 0:
        build = _docker("build", "-t", IMAGE, str(_DOCKER_CONTEXT))
        if build.returncode != 0:
            raise DockerNotAvailableError(
                f"failed to build image {IMAGE}:\n{build.stderr.strip()}"
            )

    found = _inspect_container()
    if found is None:
        _create_container()
        return
    running, container_image = found
    if container_image != IMAGE:
        # The container was created from a different image tag (the
        # Dockerfile changed since it was started). Reusing it would defeat
        # the content-hash tag entirely: every compile would keep running
        # in the stale toolchain forever. Remove and recreate.
        rm = _docker("rm", "-f", CONTAINER, timeout=60)
        if rm.returncode != 0:
            raise DockerNotAvailableError(
                f"container {CONTAINER} was created from image "
                f"{container_image!r} (expected {IMAGE}) and could not be "
                f"removed for recreation:\n{rm.stderr.strip()}"
            )
        _create_container()
        return
    if not running:
        _start_container()


def cobc_version() -> str:
    """First line of `cobc --version` from inside the container."""
    result = _docker("exec", CONTAINER, "cobc", "--version", timeout=30)
    if result.returncode != 0:
        raise DockerNotAvailableError(
            f"could not query cobc inside {CONTAINER}:\n{result.stderr.strip()}"
        )
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def compile_source(source_path: Path, coverage: bool = False) -> CompileResult:
    """Compile a free-form COBOL source file (which must live under
    WORK_ROOT) inside the container. The binary is written next to the
    source with no suffix -- it is a Linux ELF that only ever executes
    inside the container.

    `coverage=True` adds GnuCOBOL's own `--coverage` flag, which builds on
    gcc's gcov machinery (cobc transpiles COBOL to C): the resulting
    binary, once executed, writes a `.gcda` file next to itself that
    `run_gcov` (below) turns into a per-COBOL-line report. See
    docs/2026-07-17-coverage-reporting-design.md."""
    container_source = to_container_path(source_path, WORK_ROOT)
    binary_path = source_path.with_suffix("")
    container_binary = to_container_path(binary_path, WORK_ROOT)
    cmd = ["docker", "exec", CONTAINER, "cobc", "-free"]
    if coverage:
        cmd.append("--coverage")
    cmd += ["-x", container_source, "-o", container_binary]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CompileResult(
            success=False,
            binary_path=None,
            stdout="",
            stderr=(
                f"mockymock: docker exec cobc timed out after 600s "
                f"(the docker daemon may be wedged): {exc}\n"
            ),
        )
    except OSError as exc:
        return CompileResult(
            success=False,
            binary_path=None,
            stdout="",
            stderr=f"mockymock: could not run docker exec: {exc}\n",
        )
    success = result.returncode == 0 and binary_path.exists()
    return CompileResult(
        success=success,
        binary_path=binary_path if success else None,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def run_binary(binary_path: Path, timeout_seconds: int = 30) -> ExecutionResult:
    """Run a compiled binary inside the container, from its own sandbox
    directory. coreutils `timeout` enforces the limit container-side and
    exits 124 on expiry, matching TIMEOUT_EXIT_CODE; `-k 5` escalates to
    SIGKILL five seconds later so a binary that ignores SIGTERM cannot
    keep burning CPU as an orphan in the persistent container. The
    host-side subprocess timeout is a wider guard against `docker exec`
    itself hanging."""
    container_binary = to_container_path(binary_path, WORK_ROOT)
    container_dir = container_binary.rsplit("/", 1)[0]
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-w",
                container_dir,
                CONTAINER,
                "timeout",
                "-k",
                "5",
                str(timeout_seconds),
                container_binary,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            exit_code=TIMEOUT_EXIT_CODE,
            stdout=_coerce_output(exc.stdout),
            stderr=(
                _coerce_output(exc.stderr)
                + f"mockymock: docker exec did not return within "
                f"{timeout_seconds + 15}s (container-side timeout is "
                f"{timeout_seconds}s; the docker daemon may be wedged)\n"
            ),
        )
    except OSError as exc:
        return ExecutionResult(
            exit_code=NOT_FOUND_EXIT_CODE,
            stdout="",
            stderr=f"mockymock: could not run docker exec: {exc}\n",
        )
    stderr = result.stderr
    if result.returncode == TIMEOUT_EXIT_CODE:
        stderr += (
            f"mockymock: binary timed out after {timeout_seconds}s "
            f"(a mocked CALL may have removed a loop's terminating "
            f"condition, producing an infinite loop)\n"
        )
    return ExecutionResult(
        exit_code=result.returncode, stdout=result.stdout, stderr=stderr
    )


@dataclass
class GcovResult:
    success: bool
    gcov_text: str
    stderr: str


def run_gcov(source_path: Path) -> GcovResult:
    """Run gcov against the .gcda file a --coverage-compiled binary
    (compile_source(..., coverage=True)) writes once it has executed,
    returning the resulting <name>.cbl.gcov text -- a per-COBOL-line
    report `report/coverage.py`'s `parse_gcov` can turn into a
    CoverageReport.

    The .gcda file is only written by the C runtime's coverage-dump
    handler on normal process exit; a binary killed by run_binary's
    timeout SIGKILL never reaches it, so that case is detected up front
    and reported as a clean, explanatory failure rather than a confusing
    gcov error about a missing file."""
    gcda_path = source_path.with_suffix(".gcda")
    if not gcda_path.exists():
        return GcovResult(
            success=False,
            gcov_text="",
            stderr=(
                "mockymock: no coverage data produced (the binary did not "
                "exit normally, so its coverage-dump handler never ran)\n"
            ),
        )
    container_source = to_container_path(source_path, WORK_ROOT)
    container_dir = container_source.rsplit("/", 1)[0]
    try:
        result = subprocess.run(
            ["docker", "exec", "-w", container_dir, CONTAINER, "gcov", gcda_path.name],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GcovResult(
            success=False, gcov_text="", stderr=f"mockymock: gcov failed: {exc}\n"
        )
    if result.returncode != 0:
        return GcovResult(success=False, gcov_text="", stderr=result.stderr)
    gcov_path = source_path.parent / (source_path.name + ".gcov")
    if not gcov_path.exists():
        return GcovResult(
            success=False,
            gcov_text="",
            stderr=f"mockymock: gcov did not produce {gcov_path.name}\n",
        )
    return GcovResult(success=True, gcov_text=gcov_path.read_text(), stderr="")
