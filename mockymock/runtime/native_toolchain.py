"""Host-native GnuCOBOL toolchain, from a self-contained GnuCOBOL tree.

The Docker toolchain (`docker_toolchain.py`) stays the default. This one
exists so an editor integration can ship GnuCOBOL itself -- the mockymock
VS Code extension bundles a relocatable GnuCOBOL 3.2 tree per platform --
and run tests with no Docker install at all. It is selected by
`runtime/toolchain.py`, never imported directly by a command.

The tree is named by `MOCKYMOCK_GNUCOBOL_HOME` and laid out like an
installed GnuCOBOL prefix:

    <home>/bin/cobc[.exe]           the compiler (and, on Windows, gcc too)
    <home>/lib/libcob.*             libcob and the GMP it links
    <home>/include/libcob.h, gmp.h  what the generated C includes
    <home>/share/gnucobol/config    the -std=... dialect files
    <home>/share/gnucobol/copy      the bundled copybooks

cobc bakes absolute paths for every one of those in at build time, which is
exactly the "COB_CONFIG_DIR issues" the Docker-only decision (2026-07-04)
was about. Every one of them has an environment override, and `_env()` sets
them all from the tree's own location, so the tree works wherever it was
unpacked.

What this does *not* bundle is a C compiler on Linux and macOS: cobc
transpiles COBOL to C and calls the system one (`gcc` / Xcode's `clang`).
`ensure_toolchain` checks for it up front and says what to install. A
Windows tree is expected to be one of the MinGW GnuCOBOL distributions,
which carry their own gcc in `bin/`.

Threat model, compared to the container: compiled tests run as the user,
on the host, with the user's network and files. The container's hardening
flags (`docker_toolchain._HARDENING_FLAGS`) have no equivalent here; the
only guard kept is the timeout, which kills the binary's whole process
group. That is the same trust a developer extends to `cobc -x && ./prog`
on their own program, which is what the extension's users are doing.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from mockymock.runtime._proc import (
    _ACTIVE as _ACTIVE,
)
from mockymock.runtime._proc import (
    MARKER_CAPTURE_BYTES as MARKER_CAPTURE_BYTES,
)
from mockymock.runtime._proc import (
    STDERR_CAPTURE_BYTES as STDERR_CAPTURE_BYTES,
)
from mockymock.runtime._proc import (  # noqa: F401 -- re-exported
    STDOUT_CAPTURE_BYTES as STDOUT_CAPTURE_BYTES,
)
from mockymock.runtime._proc import (
    _CappedStdout as _CappedStdout,
)
from mockymock.runtime._proc import (
    _drain as _drain,
)
from mockymock.runtime._proc import (
    _not_kept_note as _not_kept_note,
)
from mockymock.runtime._proc import (
    _run as _run,
)
from mockymock.runtime._proc import (
    _run_capped as _run_capped,
)
from mockymock.runtime._proc import (
    install_termination_handler as install_termination_handler,
)
from mockymock.runtime._proc import (
    kill_active_children as kill_active_children,
)
from mockymock.runtime._proc import (
    kill_tree as kill_tree,
)
from mockymock.runtime.compiler import CompileResult
from mockymock.runtime.docker_toolchain import (
    _LIBXML_VERSION_WARNING_RE,
    DockerNotAvailableError,
    GcovResult,
)
from mockymock.runtime.executor import (
    NOT_FOUND_EXIT_CODE,
    TIMEOUT_EXIT_CODE,
    ExecutionResult,
    _coerce_output,
    binary_run_env,
)
from mockymock.runtime.reserved_words import not_reserved_flags, prepare_free_source

#: The one name every command catches; the Docker module defines it, and
#: both backends raise it, so callers stay backend-agnostic.
ToolchainNotAvailableError = DockerNotAvailableError

HOME_ENV = "MOCKYMOCK_GNUCOBOL_HOME"

#: Shown where the Docker backend shows its container name.
CONTAINER = "native"
WORK_ROOT = Path.home() / ".mockymock" / "work"

_EXE = ".exe" if sys.platform == "win32" else ""

# Same flags as the container compile; see docker_toolchain.compile_source.
_COBC_DIALECT_FLAGS: tuple[str, ...] = ("-free", "-std=mvs")

#: stderr text this module writes when the toolchain, not the program,
#: failed -- read by `mutate` the way it reads docker's own errors.
NATIVE_FAILURE_MARKERS: tuple[str, ...] = (
    "mockymock: could not run cobc",
    "mockymock: cobc timed out",
    "GnuCOBOL toolchain missing",
)


def gnucobol_home() -> Path | None:
    """The configured GnuCOBOL tree, or None when the variable is unset."""
    value = os.environ.get(HOME_ENV, "").strip()
    return Path(value).expanduser() if value else None


def _require_home() -> Path:
    home = gnucobol_home()
    if home is None:
        raise ToolchainNotAvailableError(
            f"{HOME_ENV} is not set: the native toolchain needs a GnuCOBOL "
            f"tree (the mockymock VS Code extension ships one)"
        )
    cobc = home / "bin" / f"cobc{_EXE}"
    if not cobc.is_file():
        raise ToolchainNotAvailableError(
            f"GnuCOBOL toolchain missing: no {cobc} ({HOME_ENV}={home})"
        )
    return home


def _path_prepend(var: str, *entries: Path) -> str:
    current = os.environ.get(var, "")
    parts = [str(entry) for entry in entries]
    if current:
        parts.append(current)
    return os.pathsep.join(parts)


def _tree_dir(home: Path, name: str) -> Path:
    """`<home>/share/gnucobol/<name>`, an installed prefix's layout, or
    `<home>/<name>` when only that exists: the Windows MinGW distributions
    (Arnold Trembley's) keep `config/` and `copy/` at the root, with the
    runtime modules in `extras/`."""
    installed = home / "share" / "gnucobol" / name
    flat = home / name
    return flat if not installed.is_dir() and flat.is_dir() else installed


def _env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The process environment with every path cobc and libcob baked in at
    build time pointed back into `home`. A variable the user already set
    wins, so a hand-tuned COB_CFLAGS (say) is never silently replaced."""
    bin_dir, lib_dir = home / "bin", home / "lib"
    include_dir = home / "include"
    env = dict(os.environ)
    env["PATH"] = (
        _path_prepend("PATH", bin_dir, lib_dir)
        if sys.platform == "win32"
        else (_path_prepend("PATH", bin_dir))
    )
    if sys.platform == "darwin":
        env["DYLD_LIBRARY_PATH"] = _path_prepend("DYLD_LIBRARY_PATH", lib_dir)
    elif sys.platform != "win32":
        env["LD_LIBRARY_PATH"] = _path_prepend("LD_LIBRARY_PATH", lib_dir)
    defaults = {
        "COB_CONFIG_DIR": str(_tree_dir(home, "config")),
        "COB_COPY_DIR": str(_tree_dir(home, "copy")),
        "COB_CFLAGS": (
            f'-pipe -I"{include_dir}" -Wno-unused -fsigned-char -Wno-pointer-sign'
        ),
        "COB_LDFLAGS": f'-L"{lib_dir}"',
        "COB_LIBS": f'-L"{lib_dir}" -lcob',
        "COB_LIBRARY_PATH": str(
            home / "extras" if (home / "extras").is_dir() else lib_dir / "gnucobol"
        ),
    }
    for name, value in defaults.items():
        env.setdefault(name, value)
    if extra:
        env.update(extra)
    return env


@cache
def _cobc_info(home: Path) -> dict[str, str]:
    """`cobc --info`'s KEY : value lines, once per process."""
    result = subprocess.run(
        [str(home / "bin" / f"cobc{_EXE}"), "--info"],
        env=_env(home),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise ToolchainNotAvailableError(
            f"mockymock: could not run cobc --info:\n{result.stderr.strip()}"
        )
    info: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition(":")
        if sep and re.fullmatch(r"[A-Z_]+", key.strip()):
            info.setdefault(key.strip(), value.strip())
    return info


def _c_compiler_hint() -> str:
    if sys.platform == "darwin":
        return "run `xcode-select --install` for Apple's command line tools"
    if sys.platform == "win32":
        return "the GnuCOBOL tree should carry MinGW's gcc in its bin directory"
    return (
        "install gcc (`sudo apt install gcc` / `sudo dnf install gcc` / "
        "`sudo pacman -S gcc`)"
    )


def ensure_toolchain(force_rebuild: bool = False) -> None:
    """Check the tree is there and cobc can reach a C compiler. Nothing is
    built or started, so `force_rebuild` has nothing to rebuild."""
    del force_rebuild
    home = _require_home()
    config_dir = Path(_env(home)["COB_CONFIG_DIR"])
    if not (config_dir / "default.conf").is_file():
        raise ToolchainNotAvailableError(
            f"GnuCOBOL toolchain missing its dialect files: no default.conf in "
            f"{config_dir} (set COB_CONFIG_DIR to the tree's config folder)"
        )
    info = _cobc_info(home)
    compiler = os.environ.get("COB_CC") or info.get("COB_CC") or "gcc"
    program = compiler.split()[0]
    if shutil.which(program, path=_env(home)["PATH"]) is None:
        raise ToolchainNotAvailableError(
            f"GnuCOBOL toolchain missing a C compiler: cobc "
            f"compiles through `{program}`, which is not on PATH -- "
            f"{_c_compiler_hint()}"
        )


def cobc_version(timeout: int = 30) -> str:
    home = _require_home()
    try:
        result = subprocess.run(
            [str(home / "bin" / f"cobc{_EXE}"), "--version"],
            env=_env(home),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolchainNotAvailableError(
            f"mockymock: could not run cobc: {exc}"
        ) from exc
    if result.returncode != 0:
        raise ToolchainNotAvailableError(
            f"mockymock: could not run cobc --version:\n{result.stderr.strip()}"
        )
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def docker_failure_line(stderr: str) -> str | None:
    """The first stderr line that says the toolchain failed, or None."""
    for line in stderr.splitlines():
        if any(marker in line for marker in NATIVE_FAILURE_MARKERS):
            return line.strip()
    return None


def toolchain_failure(timeout: int = 30) -> str | None:
    """Why the toolchain cannot run anything right now, or None."""
    del timeout
    try:
        _require_home()
    except ToolchainNotAvailableError as exc:
        return str(exc).splitlines()[0]
    return None


def container_identity(timeout: int = 30) -> str | None:
    """No container restarts under a native run, so there is nothing to
    tell apart; None makes `mutate` skip the restart check."""
    del timeout
    return None


def compile_source(
    source_path: Path,
    coverage: bool = False,
    trace: bool = False,
    debug: bool = False,
    extra_sources: Sequence[Path] = (),
) -> CompileResult:
    """Compile a free-form COBOL source file next to itself, with the same
    flags as the container compile. The compiler runs from the source's
    own directory for the same reason the container one uses `-w`: gcov
    bakes the `.gcno` path in from the compiler's working directory."""
    binary_path = source_path.with_suffix(_EXE)
    try:
        home = _require_home()
    except ToolchainNotAvailableError as exc:
        return CompileResult(False, None, "", f"{exc}\n")
    cmd = [
        str(home / "bin" / f"cobc{_EXE}"),
        *_COBC_DIALECT_FLAGS,
        *not_reserved_flags(_prepared(source_path, extra_sources)),
    ]
    if coverage:
        cmd.append("--coverage")
    if trace:
        cmd.append("-ftraceall")
    if debug:
        cmd.append("-g")
    # `extra_sources`: the instrumented USE REAL CALL subprograms, linked
    # into the same executable (they live in the same sandbox directory).
    cmd += [
        "-x",
        source_path.name,
        *(str(extra.relative_to(source_path.parent)) for extra in extra_sources),
        "-o",
        binary_path.name,
    ]
    # cobc's intermediate C goes to TMPDIR; keep it in the sandbox so
    # nothing a run writes outlives the sandbox's cleanup.
    env = _env(home, {"TMPDIR": str(source_path.parent)})
    if sys.platform == "win32":
        env["TEMP"] = env["TMP"] = str(source_path.parent)
    try:
        result = _run(cmd, cwd=source_path.parent, env=env, timeout=600, text=True)
    except subprocess.TimeoutExpired:
        return CompileResult(False, None, "", "mockymock: cobc timed out after 600s\n")
    except OSError as exc:
        return CompileResult(False, None, "", f"mockymock: could not run cobc: {exc}\n")
    success = result.returncode == 0 and binary_path.exists()
    return CompileResult(
        success=success,
        returncode=result.returncode,
        binary_path=binary_path if success else None,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def run_binary(
    binary_path: Path,
    timeout_seconds: int = 30,
    trace_path: Path | None = None,
) -> ExecutionResult:
    """Run a compiled binary from its own sandbox directory, killing its
    process group once `timeout_seconds` pass (exit 124, as in the
    container)."""
    timeout_seconds = max(1, int(timeout_seconds))
    try:
        home = _require_home()
    except ToolchainNotAvailableError as exc:
        return ExecutionResult(NOT_FOUND_EXIT_CODE, "", f"{exc}\n")
    extra: dict[str, str] = binary_run_env()
    if trace_path is not None:
        extra |= {
            "COB_SET_TRACE": "yes",
            "COB_TRACE_FILE": str(trace_path),
            "COB_TRACE_FORMAT": "%P|%S|%L",
        }
    try:
        exit_code, stdout, stderr, dropped = _run_capped(
            [str(binary_path)],
            cwd=binary_path.parent,
            env=_env(home, extra),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            exit_code=TIMEOUT_EXIT_CODE,
            stdout=_coerce_output(exc.stdout),
            stderr=(
                _coerce_output(exc.stderr)
                + _not_kept_note(getattr(exc, "not_kept", 0))
                + f"mockymock: binary timed out after {timeout_seconds}s "
                f"(a mocked CALL may have removed a loop's terminating "
                f"condition, producing an infinite loop)\n"
            ),
        )
    except OSError as exc:
        return ExecutionResult(
            NOT_FOUND_EXIT_CODE, "", f"mockymock: could not run {binary_path}: {exc}\n"
        )
    if exit_code < 0:
        # Killed by a signal: report it the way a shell (and so the
        # container's `docker exec`) does, 128 + signal number.
        exit_code = 128 - exit_code
    return ExecutionResult(
        exit_code=exit_code,
        stdout=_coerce_output(stdout),
        stderr=_LIBXML_VERSION_WARNING_RE.sub("", _coerce_output(stderr))
        + _not_kept_note(dropped),
    )


def _resolve(program: str, env: dict[str, str]) -> str | None:
    """`program` looked up on the PATH of `env`, the one the child gets.
    Windows' CreateProcess searches the *parent's* PATH for a bare name and
    ignores `env=`, so the tree's own gcov/gdb are only found this way."""
    return shutil.which(program, path=env["PATH"])


def _gcov_program(env: dict[str, str]) -> str:
    program = os.environ.get("MOCKYMOCK_GCOV") or "gcov"
    return _resolve(program, env) or program


def run_gcov(source_path: Path) -> GcovResult:
    """gcov over the `.gcda` a `--coverage` binary wrote; see the Docker
    module's `run_gcov` for why a missing `.gcda` is reported up front."""
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
    try:
        env = _env(_require_home())
        result = _run(
            [_gcov_program(env), gcda_path.name],
            cwd=source_path.parent,
            env=env,
            timeout=60,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired, ToolchainNotAvailableError) as exc:
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
    """`gdb --interpreter=mi2` on the host, the same MI session the
    container one gives `debug/gdb_session.py`. Needs gdb on PATH (macOS
    ships lldb, not gdb, so debugging there needs `brew install gdb`)."""
    home = _require_home()
    env = _env(home)
    gdb = _resolve("gdb", env)
    if gdb is None:
        raise ToolchainNotAvailableError(
            "GnuCOBOL toolchain missing gdb: the debugger drives "
            "gdb, which is not on PATH"
        )
    return subprocess.Popen(
        [gdb, "-q", "--interpreter=mi2", str(binary_path)],
        cwd=binary_path.parent,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


@dataclass(frozen=True)
class NativeFacts:
    """What `runtime/status.py` reports for this backend."""

    home: Path | None
    c_compiler: str | None


def facts() -> NativeFacts:
    home = gnucobol_home()
    compiler = None
    if home is not None and (home / "bin" / f"cobc{_EXE}").is_file():
        try:
            compiler = os.environ.get("COB_CC") or _cobc_info(home).get("COB_CC")
        except (ToolchainNotAvailableError, OSError, subprocess.TimeoutExpired):
            compiler = None
    return NativeFacts(home=home, c_compiler=compiler)


def _prepared(source_path: Path, extra_sources: Sequence[Path]) -> str:
    """Prepare every source cobc compiles (`prepare_free_source`); the
    program's own text."""
    for extra in extra_sources:
        prepare_free_source(extra)
    return prepare_free_source(source_path)
