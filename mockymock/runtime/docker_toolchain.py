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
import re
import subprocess
from collections.abc import Sequence
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


def _image_tag(
    dockerfile_text: str | None = None,
    hardening_flags: tuple[str, ...] | None = None,
) -> str:
    """8-char content hash of docker/Dockerfile PLUS the hardening flags
    `docker run` applies at container-creation time, used as the image
    tag so that editing EITHER changes the tag, `docker image inspect`
    misses, and `ensure_toolchain` rebuilds/recreates instead of silently
    reusing a stale image or a running container whose hardening no
    longer matches what's in source. The flags are never baked into the
    Dockerfile itself, so without folding them in here, editing
    _HARDENING_FLAGS alone left IMAGE -- and therefore
    ensure_toolchain's only recreate signal -- unchanged: an
    already-running container would silently keep whatever hardening it
    started with (audit finding F2)."""
    if dockerfile_text is None:
        dockerfile_text = (_DOCKER_CONTEXT / "Dockerfile").read_text(encoding="utf-8")
    if hardening_flags is None:
        hardening_flags = _HARDENING_FLAGS
    digest_input = dockerfile_text + "\x00" + "\x00".join(hardening_flags)
    return hashlib.sha256(digest_input.encode()).hexdigest()[:8]


IMAGE = f"mockymock-gnucobol:{_image_tag()}"
CONTAINER = "mockymock-cobc"
WORK_ROOT = Path.home() / ".mockymock" / "work"


class DockerNotAvailableError(RuntimeError):
    """Raised when the Docker daemon (or CLI) cannot be reached or the
    toolchain image/container cannot be brought up."""


#: The backend-neutral name `runtime/toolchain.py` documents; the native
#: backend raises the same class.
ToolchainNotAvailableError = DockerNotAvailableError


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


def _inspect_container(timeout: int = 30) -> tuple[bool, str] | None:
    """Return (running, image) for the toolchain container, or None if no
    container with that name exists. `timeout` is overridable so the
    dashboard's read-only probe can enforce its own shorter PROBE_TIMEOUT
    (2026-08-12 audit Finding 18)."""
    state = _docker(
        "inspect", "-f", _CONTAINER_INSPECT_FORMAT, CONTAINER, timeout=timeout
    )
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


def _create_container(_recreate_on_stale: bool = True) -> None:
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
                running, image = found
                if image != IMAGE:
                    # The race winner was a DIFFERENT installed version
                    # (different Dockerfile/hardening flags -> different
                    # content-hash tag). Adopting its container would
                    # bypass the stale-image safeguard ensure_toolchain's
                    # main path enforces (2026-08-12 audit Finding 17) --
                    # remove and recreate once, same as that path.
                    if not _recreate_on_stale:
                        raise DockerNotAvailableError(
                            f"container {CONTAINER} keeps reappearing with "
                            f"image {image!r} (expected {IMAGE}) -- another "
                            f"mockymock version is racing this one; retry "
                            f"when it is done"
                        )
                    rm = _docker("rm", "-f", CONTAINER, timeout=60)
                    if (
                        rm.returncode != 0
                        and "no such container" not in rm.stderr.lower()
                    ):
                        raise DockerNotAvailableError(
                            f"container {CONTAINER} was created from image "
                            f"{image!r} (expected {IMAGE}) and could not be "
                            f"removed for recreation:\n{rm.stderr.strip()}"
                        )
                    _create_container(_recreate_on_stale=False)
                    return
                if running:
                    return
                _start_container()
                return
        raise DockerNotAvailableError(
            f"failed to start container {CONTAINER}:\n{run.stderr.strip()}"
        )


def ensure_toolchain(force_rebuild: bool = False) -> None:
    """Bring the toolchain up: daemon reachable, image built, container
    running *and created from the current image*. Idempotent; called by
    both `mockymock setup` and every `mockymock run` (so the container is
    restarted if it died, and recreated if docker/Dockerfile changed --
    the content-hash tag in IMAGE only helps if a stale container is not
    silently reused).

    `force_rebuild` (only ever passed by `mockymock setup --rebuild`,
    never by the implicit per-run call) rebuilds even when an image
    already exists for the current content-hash tag, with `--no-cache
    --pull` so a change in the *base* image (not just this repo's
    Dockerfile, which the content hash already catches) is picked up
    too."""
    info = _docker("info", timeout=30)
    if info.returncode != 0:
        raise DockerNotAvailableError(f"{_DAEMON_HINT}\n{info.stderr.strip()}")

    image = _docker("image", "inspect", IMAGE, timeout=30)
    if image.returncode != 0 or force_rebuild:
        build_args = ["build", "-t", IMAGE]
        if force_rebuild:
            build_args += ["--no-cache", "--pull"]
        build_args.append(str(_DOCKER_CONTEXT))
        build = _docker(*build_args)
        if build.returncode != 0:
            raise DockerNotAvailableError(
                f"failed to build image {IMAGE}:\n{build.stderr.strip()}"
            )
        if force_rebuild:
            # `docker build -t IMAGE` re-tags the same content-hash tag
            # onto the *new* image ID, so the stale-image check below
            # (which compares tag strings) would keep a container created
            # from the old image -- and every subsequent compile would
            # still run in the toolchain the user just asked to replace.
            # Drop the container unconditionally so it is recreated from
            # the freshly built image.
            rm = _docker("rm", "-f", CONTAINER, timeout=60)
            if rm.returncode != 0 and "no such container" not in rm.stderr.lower():
                raise DockerNotAvailableError(
                    f"image {IMAGE} was rebuilt but container {CONTAINER} "
                    f"could not be removed for recreation:\n{rm.stderr.strip()}"
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
        if rm.returncode != 0 and "no such container" not in rm.stderr.lower():
            raise DockerNotAvailableError(
                f"container {CONTAINER} was created from image "
                f"{container_image!r} (expected {IMAGE}) and could not be "
                f"removed for recreation:\n{rm.stderr.strip()}"
            )
        # "No such container" means a concurrent invocation racing on the
        # same stale-image check already removed it -- same race as the
        # "already in use" recovery below, just on the other end of the
        # remove-then-recreate sequence. Proceed to create/adopt either way.
        _create_container()
        return
    if not running:
        _start_container()


#: Text the docker CLI (or this module, on its own client-side failures)
#: writes to stderr when the toolchain itself failed rather than the COBOL
#: it was asked to compile or run. A compile or run carrying one of these
#: says nothing about the program, so a caller that scores verdicts
#: (`mockymock mutate`) must not read it as one (issue #347).
DOCKER_FAILURE_MARKERS: tuple[str, ...] = (
    "Error response from daemon",
    "Cannot connect to the Docker daemon",
    "No such container",
    "mockymock: could not run docker exec",
    "the docker daemon may be wedged",
)


def docker_failure_line(stderr: str) -> str | None:
    """The first stderr line that says the toolchain failed, or None."""
    for line in stderr.splitlines():
        if any(marker in line for marker in DOCKER_FAILURE_MARKERS):
            return line.strip()
    return None


def toolchain_failure(timeout: int = 30) -> str | None:
    """Why the toolchain container cannot run anything right now, or None
    when it is up. Read-only: unlike `ensure_toolchain` it never starts,
    builds or recreates anything, so it is cheap enough to ask after every
    compile or run whose outcome could have been the container dying under
    it rather than the program's own doing."""
    try:
        found = _inspect_container(timeout=timeout)
    except DockerNotAvailableError as exc:
        return str(exc).splitlines()[0]
    if found is None:
        return f"container {CONTAINER} no longer exists"
    running, _ = found
    if not running:
        return f"container {CONTAINER} stopped"
    return None


def container_identity(timeout: int = 30) -> str | None:
    """The toolchain container's ID and start time, or None when it cannot
    be inspected. Two reads around a compile+run that differ mean the
    container was restarted in between -- by another `mutate --jobs`
    worker, typically -- so the run was cut off even though the container
    is up again by the time anyone asks `toolchain_failure()`."""
    state = _docker(
        "inspect", "-f", "{{.Id}} {{.State.StartedAt}}", CONTAINER, timeout=timeout
    )
    if state.returncode != 0:
        return None
    return state.stdout.strip() or None


def cobc_version(timeout: int = 30) -> str:
    """First line of `cobc --version` from inside the container.
    `timeout` is overridable for the dashboard probe (Finding 18)."""
    result = _docker("exec", CONTAINER, "cobc", "--version", timeout=timeout)
    if result.returncode != 0:
        raise DockerNotAvailableError(
            f"could not query cobc inside {CONTAINER}:\n{result.stderr.strip()}"
        )
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def compile_source(
    source_path: Path,
    coverage: bool = False,
    trace: bool = False,
    debug: bool = False,
    extra_sources: Sequence[Path] = (),
) -> CompileResult:
    """Compile a free-form COBOL source file (which must live under
    WORK_ROOT) inside the container. The binary is written next to the
    source with no suffix -- it is a Linux ELF that only ever executes
    inside the container.

    `coverage=True` adds GnuCOBOL's own `--coverage` flag, which builds on
    gcc's gcov machinery (cobc transpiles COBOL to C): the resulting
    binary, once executed, writes a `.gcda` file next to itself that
    `run_gcov` (below) turns into a per-COBOL-line report. See
    docs/2026-07-17-coverage-reporting-design.md.

    `debug=True` adds `-g`, enabling gdb to set breakpoints directly
    against the compiled `.cbl` (verified empirically -- see
    docs/2026-07-22-dap-debugger-design.md's Empirical basis). This also
    causes cobc to emit a sibling `<name>.c.l.h` header with a COBOL-name
    comment on every generated local variable declaration, which
    `mockymock/debug/variable_map.py` parses. Orthogonal to `coverage` and
    `trace`; a debug session needs neither.

    `-w container_dir` pins the compiler process's working directory to
    the source's own per-run sandbox, mirroring `run_binary` below. This
    matters specifically for `coverage=True`: gcov's machinery bakes the
    `.gcno` path into the compiled binary based on the *compiler's* CWD
    at compile time, not the absolute `-x`/`-o` paths passed on the
    command line. Without `-w`, cobc compiles with the container's
    default `WORKDIR /work` (see mockymock/runtime/docker/Dockerfile) as
    its CWD, so the `.gcno`/`.gcda` pair silently lands at the shared
    `/work` root instead of next to the sandboxed source -- `run_gcov`
    then never finds it there and always reports "no coverage data
    produced", even though the binary ran and exited normally.
    """
    container_source = to_container_path(source_path, WORK_ROOT)
    binary_path = source_path.with_suffix("")
    container_binary = to_container_path(binary_path, WORK_ROOT)
    container_dir = container_source.rsplit("/", 1)[0]
    # Wrapped in the same in-container `timeout -k` run_binary uses for
    # the execute phase: without it, the host-side subprocess.run(timeout=)
    # below only kills the LOCAL `docker exec` client on expiry -- a
    # pathological source that makes cobc hang leaves it orphaned inside
    # the shared, long-lived container, burning CPU/PIDS_LIMIT against
    # every other run sharing it (audit finding F1). 585s leaves a 15s
    # margin under the host-side 600s guard, the same ratio run_binary
    # uses between its container and host timeouts.
    cmd = [
        "docker",
        "exec",
        "-w",
        container_dir,
        CONTAINER,
        "timeout",
        "-k",
        "5",
        "585",
        "cobc",
        "-free",
        # GnuCOBOL's default dialect doesn't implement the IBM
        # compiler-directing statements (EJECT, SKIP1/SKIP2/SKIP3) that
        # real z/OS mainframe sources use between paragraphs/sections --
        # `-std=mvs` is what makes those compile instead of erroring out.
        "-std=mvs",
    ]
    if coverage:
        cmd.append("--coverage")
    if trace:
        # -ftraceall only *generates* the trace hooks. It emits nothing on
        # its own -- COB_SET_TRACE at run time is what actually turns
        # tracing on (see run_binary's trace_path).
        cmd.append("-ftraceall")
    if debug:
        cmd.append("-g")
    # `extra_sources` (USE REAL CALL, docs/2026-11-01-real-call-integration-
    # design.md): the instrumented real subprograms, compiled into the same
    # executable so the program's CALL resolves to them.
    cmd += [
        "-x",
        container_source,
        *(to_container_path(extra, WORK_ROOT) for extra in extra_sources),
        "-o",
        container_binary,
    ]
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


#: libxml2's own startup check, printed by every binary the image's Debian
#: GnuCOBOL build links (`Warning: program compiled against libxml 212
#: using older 209`). Harmless -- libcob runs fine against the older
#: library -- but it reached the console on every run, passing ones
#: included, and read as something broken.
_LIBXML_VERSION_WARNING_RE = re.compile(
    r"^Warning: program compiled against libxml \d+ using older \d+\r?\n?",
    re.MULTILINE,
)


def run_binary(
    binary_path: Path,
    timeout_seconds: int = 30,
    trace_path: Path | None = None,
) -> ExecutionResult:
    """Run a compiled binary inside the container, from its own sandbox
    directory. coreutils `timeout` enforces the limit container-side and
    exits 124 on expiry, matching TIMEOUT_EXIT_CODE; `-k 5` escalates to
    SIGKILL five seconds later so a binary that ignores SIGTERM cannot
    keep burning CPU as an orphan in the persistent container. The
    host-side subprocess timeout is a wider guard against `docker exec`
    itself hanging."""
    # `timeout 0` disables the container-side kill (issue #306): no caller
    # may switch off what keeps a hung binary from becoming an orphan.
    timeout_seconds = max(1, int(timeout_seconds))
    container_binary = to_container_path(binary_path, WORK_ROOT)
    container_dir = container_binary.rsplit("/", 1)[0]
    trace_env: list[str] = []
    if trace_path is not None:
        # COB_TRACE_FILE must point inside the bind-mounted sandbox or the
        # host can never read the trace back. It is also always set
        # explicitly: left unset, GnuCOBOL can spill trace onto stderr and
        # pollute the run's diagnostics. Trace never reaches stdout, so the
        # __MOCKYMOCK__ protocol stays parseable either way.
        trace_env = [
            "-e",
            "COB_SET_TRACE=yes",
            "-e",
            f"COB_TRACE_FILE={to_container_path(trace_path, WORK_ROOT)}",
            "-e",
            "COB_TRACE_FORMAT=%P|%S|%L",
        ]
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-w",
                container_dir,
                *trace_env,
                CONTAINER,
                "timeout",
                "-k",
                "5",
                str(timeout_seconds),
                container_binary,
            ],
            # Bytes, decoded below -- not text=True. Text mode decodes
            # strictly, so one DISPLAY of a field holding a non-UTF-8 byte
            # (HIGH-VALUES, a COMP field, an EBCDIC-ish literal) raised
            # UnicodeDecodeError out of the whole run; and its universal
            # newlines turned a lone CR inside a DISPLAYed value into LF,
            # cutting a __MOCKYMOCK__ FAIL/RECORD marker in two before
            # parse_stdout's LF-only split ever saw it.
            capture_output=True,
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
    stderr = _LIBXML_VERSION_WARNING_RE.sub("", _coerce_output(result.stderr))
    if result.returncode == TIMEOUT_EXIT_CODE:
        stderr += (
            f"mockymock: binary timed out after {timeout_seconds}s "
            f"(a mocked CALL may have removed a loop's terminating "
            f"condition, producing an infinite loop)\n"
        )
    return ExecutionResult(
        exit_code=result.returncode,
        stdout=_coerce_output(result.stdout),
        stderr=stderr,
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
            [
                "docker",
                "exec",
                "-w",
                container_dir,
                CONTAINER,
                "timeout",
                "-k",
                "5",
                "50",
                "gcov",
                gcda_path.name,
            ],
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
    return GcovResult(
        success=True, gcov_text=gcov_path.read_text(encoding="utf-8"), stderr=""
    )


def start_gdb_session(binary_path: Path) -> subprocess.Popen:
    """Spawn a long-lived `gdb --interpreter=mi2` process attached to a
    `debug=True`-compiled binary inside the container, returning a live
    handle instead of a completed result -- the first function in this
    module that does not follow the "run to completion" pattern every
    other function here uses (compile_source/run_binary/run_gcov all
    invoke `docker exec`, wait, and return).

    Verified empirically (docs/2026-07-22-dap-debugger-design.md): MI over
    `docker exec -i` works with no TTY and no `gdbserver`/`target remote`
    transport needed, and ptrace works under the container's existing
    hardening flags (gdb tracing its own forked child does not need
    CAP_SYS_PTRACE). The caller (`mockymock/debug/gdb_session.py`) owns
    reading/writing this process's stdio and closing it.
    """
    container_binary = to_container_path(binary_path, WORK_ROOT)
    container_dir = container_binary.rsplit("/", 1)[0]
    return subprocess.Popen(
        [
            "docker",
            "exec",
            "-i",
            "-w",
            container_dir,
            CONTAINER,
            "gdb",
            "-q",
            "--interpreter=mi2",
            container_binary,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # A DISPLAY of an uninitialized/garbage alphanumeric field -- the
        # exact thing someone debugging a data bug would inspect -- can
        # contain a byte that isn't valid in the default strict decoding,
        # which raised an uncaught UnicodeDecodeError deep inside
        # GdbSession.readline() and killed the whole session (audit
        # finding F5). errors="replace" degrades that one line instead of
        # crashing, matching runtime/executor.py's existing convention
        # for decoding subprocess output that may contain garbage bytes.
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
