"""Run one oracle job's pack, and the claim / run / report loop.

A job's pack is the load module's integration-test pack (``src/``,
``copybooks/``, ``mockymock.toml``) plus ``oracle.json``::

    {"version": 1, "kind": "baseline" | "compare", "load_module": "PAYMOD",
     "copybook_path": "copybooks",
     "suites": [{"entry": "PAYMAIN", "program": "src/PAYMAIN.cbl",
                 "cut": "tests/PAYMAIN.cut",
                 "generate": "mockymock generate src/PAYMAIN.cbl --real src/X.cbl",
                 "baseline": "baselines/PAYMAIN.json" | null}]}

For each suite the runner scaffolds the ``.cut`` with the ``generate``
command when the pack has none (a first baseline), then runs it:

* a baseline job: ``mockymock run PROGRAM --cut CUT --record-baseline FILE``,
  and reports the baseline document with the ``.cut`` text it ran, which the
  backend freezes so every later compare uses the same mocks;
* a compare job: ``mockymock run ... --baseline FILE --baseline-json FILE``,
  and reports the comparison;
* a tests job (LegacyLens "integration tests"): when the suite is marked
  ``"record": true`` (freshly scaffolded, its expected values still ``STUB
  EXPECT`` placeholders), ``mockymock run --record-expectations`` first fills
  them from what the code does now; then ``mockymock run --json-report FILE``
  plays the suite and the runner reports the per-case report with the
  ``.cut`` text it ran, which the backend keeps as the module's tests.
  The same run measures paragraph and branch coverage
  (``--branch-coverage``), reported as the suite's ``coverage``.
  A suite with ``"level": 2`` is scaffolded with ``generate --real-files``
  (its sequential files real); the data and golden files its ``.cut``
  names come back in ``files`` (base64), for the backend to keep.

A tests job may also list ``jobs`` (integration tests level 3)::

    "jobs": [{"name": "CUSTJOB", "jcl": "jcl/CUSTJOB.jcl",
              "data": "jobs/CUSTJOB/data", "expected": "jobs/CUSTJOB/expected",
              "record": true}]

Each runs as ``mockymock job`` over the pack's ``src/``; the job report and
the input and expected datasets come back in ``jobs``.

Each mockymock command runs as a child process (``python -m mockymock``)
with a timeout, so one suite that hangs or crashes does not take the
runner down. Every path the manifest names must stay inside the pack.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from mockymock.runner.client import RunnerClient, RunnerClientError
from mockymock.runner.logs import LOGGER, JobLog, environment

MANIFEST = "oracle.json"
MANIFEST_VERSION = 1
#: Job kinds a manifest may name.
KINDS = ("baseline", "compare", "tests")
#: Characters of a command's output kept in a suite's log.
MAX_LOG_CHARS = 20_000
#: Seconds one `mockymock generate` or `mockymock run` may take.
DEFAULT_SUITE_TIMEOUT = 900
#: What `mockymock run --record-expectations` prints once it has recorded
#: (it never does when the suite did not compile or was refused).
RECORDED_MARK = "--record-expectations: recorded "
#: Largest pack the runner unpacks (compressed and uncompressed).
MAX_PACK_BYTES = 200 * 1024 * 1024

#: Flags of the manifest's `generate` command the runner passes on.
_GENERATE_PATH_FLAGS = {"--real"}
_GENERATE_SWITCHES = {"--real-files"}
#: Largest data or golden file a suite or job reports back.
MAX_REPORTED_FILE_BYTES = 5 * 1024 * 1024
_GENERATE_SCENARIOS = {"happy", "branches", "all"}

#: How mockymock itself is started for a suite: this interpreter's module.
DEFAULT_COMMAND: tuple[str, ...] = (sys.executable, "-m", "mockymock")


class JobPackError(Exception):
    """The pack or its manifest is unusable; the whole job fails."""


@dataclass
class SuiteOutcome:
    """What one suite produced, as the backend's result payload takes it."""

    entry: str
    cut_path: str
    cut_text: str = ""
    exit_code: int | None = None
    log: str = ""
    baseline: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None
    #: A tests job: the ``--json-report`` document (per-case status).
    report: dict[str, Any] | None = None
    #: A tests job: whether ``--record-expectations`` filled the suite first.
    recorded: bool = False
    error: str | None = None
    #: Wall time of the suite's generate and run, in milliseconds.
    duration_ms: int | None = None
    #: A tests job: the ``--branch-coverage`` document.
    coverage: dict[str, Any] | None = None
    #: A level-2 suite: data and golden files its .cut names (path -> base64).
    files: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "entry": self.entry,
            "cut_path": self.cut_path,
            "cut_text": self.cut_text,
            "exit_code": self.exit_code,
            "log": self.log[-MAX_LOG_CHARS:],
        }
        if self.duration_ms is not None:
            out["duration_ms"] = self.duration_ms
        if self.baseline is not None:
            out["baseline"] = self.baseline
        if self.comparison is not None:
            out["comparison"] = self.comparison
        if self.report is not None:
            out["report"] = self.report
            out["recorded"] = self.recorded
        if self.coverage is not None:
            out["coverage"] = self.coverage
        if self.files is not None:
            out["files"] = self.files
        if self.error:
            out["error"] = self.error
        return out


@dataclass
class _Step:
    exit_code: int | None
    log: str
    timed_out: bool = False
    extra: list[str] = field(default_factory=list)
    duration_ms: int = 0


def extract_pack(content: bytes, target: Path) -> Path:
    """Unpack ``content`` into ``target``; the folder holding ``oracle.json``.

    Raises:
        JobPackError: Not a zip, too big, an entry escapes ``target``, or no
            manifest.
    """
    if len(content) > MAX_PACK_BYTES:
        raise JobPackError(f"pack is {len(content)} bytes, over {MAX_PACK_BYTES}")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise JobPackError(f"pack is not a zip: {exc}") from exc
    with archive:
        infos = archive.infolist()
        if sum(info.file_size for info in infos) > MAX_PACK_BYTES:
            raise JobPackError("pack unpacks to more than the size limit")
        root = target.resolve()
        for info in infos:
            name = PurePosixPath(info.filename)
            destination = (root / Path(*name.parts)).resolve() if name.parts else root
            if name.is_absolute() or not destination.is_relative_to(root):
                raise JobPackError(f"pack entry escapes the pack: {info.filename}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise JobPackError(f"pack entry is a symbolic link: {info.filename}")
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                content = archive.read(info)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
                # A corrupt member (bad CRC, a size that lies) or an
                # unsupported compression or encryption: the pack is
                # unusable, which the job reports, not a runner crash.
                raise JobPackError(
                    f"pack entry cannot be read: {info.filename}: {exc}"
                ) from exc
            destination.write_bytes(content)
    manifests = sorted(root.rglob(MANIFEST), key=lambda p: len(p.parts))
    if not manifests:
        raise JobPackError(f"pack has no {MANIFEST}")
    return manifests[0].parent


def _inside(pack: Path, relative: object, what: str) -> Path:
    """``pack / relative``, refusing a path that leaves the pack."""
    if not isinstance(relative, str) or not relative.strip():
        raise JobPackError(f"{what} is missing")
    candidate = PurePosixPath(relative)
    resolved = (pack / Path(*candidate.parts)).resolve()
    if candidate.is_absolute() or not resolved.is_relative_to(pack.resolve()):
        raise JobPackError(f"{what} leaves the pack: {relative}")
    return resolved


def load_manifest(pack: Path) -> dict[str, Any]:
    """The pack's ``oracle.json``, checked.

    Raises:
        JobPackError: Unreadable, an unknown version or kind, or no suites.
    """
    try:
        manifest = json.loads((pack / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JobPackError(f"cannot read {MANIFEST}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise JobPackError(f"{MANIFEST} is not an object")
    if manifest.get("version") != MANIFEST_VERSION:
        raise JobPackError(
            f"{MANIFEST} version {manifest.get('version')!r} is not supported"
        )
    if manifest.get("kind") not in KINDS:
        raise JobPackError(f"{MANIFEST} kind {manifest.get('kind')!r} is unknown")
    suites = manifest.get("suites")
    jobs = manifest.get("jobs")
    if suites is None and jobs:
        suites = manifest["suites"] = []
    if jobs is not None and (
        manifest.get("kind") != "tests"
        or not isinstance(jobs, list)
        or not all(isinstance(job, dict) for job in jobs)
    ):
        raise JobPackError(f"{MANIFEST} jobs must be a list of objects in a tests job")
    if not isinstance(suites, list) or not (suites or jobs):
        raise JobPackError(f"{MANIFEST} lists no suites")
    if not all(isinstance(suite, dict) for suite in suites):
        raise JobPackError(f"{MANIFEST} suites must be objects")
    return manifest


def _generate_args(pack: Path, command: object) -> list[str]:
    """The manifest's ``mockymock generate ...`` as arguments after the
    executable, with every path checked to stay inside the pack."""
    if not isinstance(command, str):
        raise JobPackError("the suite has no .cut and no generate command")
    tokens = shlex.split(command)
    if tokens[:2] != ["mockymock", "generate"] or len(tokens) < 3:
        raise JobPackError(f"not a mockymock generate command: {command}")
    args = ["generate"]
    rest = tokens[2:]
    _inside(pack, rest[0], "generate program")
    args.append(rest[0])
    index = 1
    while index < len(rest):
        flag = rest[index]
        if flag == "--scenarios" and index + 1 < len(rest):
            if rest[index + 1] not in _GENERATE_SCENARIOS:
                raise JobPackError(
                    f"generate --scenarios not allowed: {rest[index + 1]}"
                )
            args += [flag, rest[index + 1]]
            index += 2
            continue
        if flag in _GENERATE_SWITCHES:
            if flag not in args:
                args.append(flag)
            index += 1
            continue
        if flag not in _GENERATE_PATH_FLAGS or index + 1 >= len(rest):
            raise JobPackError(f"generate argument not allowed: {flag}")
        _inside(pack, rest[index + 1], f"generate {flag}")
        args += [flag, rest[index + 1]]
        index += 2
    return args


def _run_step(
    command: Sequence[str], args: list[str], cwd: Path, timeout: float
) -> _Step:
    started = time.monotonic()
    step = _run_step_timed(command, args, cwd, timeout)
    step.duration_ms = int((time.monotonic() - started) * 1000)
    return step


def _run_step_timed(
    command: Sequence[str], args: list[str], cwd: Path, timeout: float
) -> _Step:
    try:
        proc = subprocess.Popen(
            [*command, *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=sys.platform != "win32",
        )
    except OSError as exc:
        return _Step(None, f"cannot start {command[0]}: {exc}\n")
    with proc:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stdout, stderr = _stop(proc)
            # stderr too: what mockymock said before it was stopped (a
            # traceback, the toolchain's complaint) is most of what tells
            # a timeout apart from a hang.
            return _Step(
                None,
                (stdout or "")
                + (stderr or "")
                + f"\n(timed out after {timeout:.0f}s)\n",
                True,
            )
    return _Step(proc.returncode, (stdout or "") + (stderr or ""))


#: How long a timed-out mockymock gets, after SIGTERM, to kill its own
#: cobc and test binary before the runner kills its process group.
TERMINATE_GRACE_SECONDS = 10.0


def _stop(proc: subprocess.Popen) -> tuple[str, str]:
    """Stop a timed-out mockymock: SIGTERM first, which makes it kill the
    cobc / test binary it runs in their own sessions (a plain kill left
    HUGE01's compiler running for 20 minutes, stress test 2026-11-02),
    then SIGKILL to its whole process group."""
    if sys.platform == "win32":
        proc.kill()
        return proc.communicate()
    import os
    import signal

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        return proc.communicate(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        return proc.communicate()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def run_suite(
    pack: Path,
    manifest: dict[str, Any],
    suite: dict[str, Any],
    command: Sequence[str] = DEFAULT_COMMAND,
    timeout: float = DEFAULT_SUITE_TIMEOUT,
    job_log: JobLog | None = None,
) -> SuiteOutcome:
    """Run one suite of the manifest. Problems specific to the suite are
    reported in the outcome's ``error``, never raised; every step goes to
    ``job_log``."""
    entry = str(suite.get("entry") or "")
    cut_name = str(suite.get("cut") or "")
    job_log = job_log or JobLog()
    started = time.monotonic()
    job_log.event("suite started", entry=entry, cut=cut_name)
    outcome = _run_suite(pack, manifest, suite, command, timeout, job_log)
    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    if outcome.error:
        job_log.warning(
            "suite failed",
            entry=entry,
            error=outcome.error,
            exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms,
        )
    else:
        job_log.event(
            "suite finished",
            entry=entry,
            result=_finished_text(outcome),
            exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms,
        )
    return outcome


def _finished_text(outcome: SuiteOutcome) -> str:
    """How a suite that ran is summed up in the job's timeline."""
    if outcome.baseline is not None:
        return "baseline recorded"
    if outcome.report is not None:
        statuses = [
            str(case.get("status"))
            for case in outcome.report.get("cases") or []
            if isinstance(case, dict)
        ]
        counted = [
            f"{statuses.count(status)} {status.replace('_', ' ')}"
            for status in ("passed", "failed", "crashed", "not_run")
            if status in statuses
        ]
        return ", ".join(counted) or "no cases"
    return "matches" if (outcome.comparison or {}).get("matches") else "differs"


def _run_suite(
    pack: Path,
    manifest: dict[str, Any],
    suite: dict[str, Any],
    command: Sequence[str],
    timeout: float,
    job_log: JobLog,
) -> SuiteOutcome:
    entry = str(suite.get("entry") or "")
    cut_name = str(suite.get("cut") or "")
    outcome = SuiteOutcome(entry=entry, cut_path=cut_name)
    kind = manifest["kind"]
    try:
        program = _inside(pack, suite.get("program"), "program")
        cut = _inside(pack, cut_name, "cut")
        copybooks = _inside(
            pack, manifest.get("copybook_path") or "copybooks", "copybook_path"
        )
        baseline_file = (
            _inside(pack, suite.get("baseline"), "baseline")
            if kind == "compare" and suite.get("baseline")
            else None
        )
        generate = (
            None if cut.is_file() else _generate_args(pack, suite.get("generate"))
        )
        if generate is not None and kind == "tests" and suite.get("level") == 2:
            if "--real-files" not in generate:
                generate.append("--real-files")
    except JobPackError as exc:
        outcome.error = str(exc)
        return outcome
    if kind == "compare" and (baseline_file is None or not baseline_file.is_file()):
        outcome.error = "no baseline for this suite: record a new baseline first"
        return outcome
    if kind == "compare" and generate is not None:
        outcome.error = "the baseline's .cut is missing from the pack"
        return outcome

    log: list[str] = []
    if generate is not None:
        cut.parent.mkdir(parents=True, exist_ok=True)
        step = _run_step(
            command,
            [*generate, "-o", cut_name, "--force", "--copybook-path", str(copybooks)],
            pack,
            timeout,
        )
        log.append(f"$ mockymock {' '.join(generate)}\n{step.log}")
        job_log.event(
            "generate finished",
            level=logging.WARNING if step.exit_code != 0 else logging.INFO,
            entry=entry,
            exit_code=step.exit_code,
            timed_out=step.timed_out or None,
            duration_ms=step.duration_ms,
            command=f"mockymock {' '.join(generate)}",
        )
        if not cut.is_file():
            outcome.exit_code = step.exit_code
            outcome.log = "".join(log)
            outcome.error = "mockymock generate did not write the .cut"
            return outcome
    if kind == "tests":
        return _run_tests_suite(
            pack,
            suite,
            program,
            cut,
            copybooks,
            command,
            timeout,
            job_log,
            outcome,
            log,
        )
    outcome.cut_text = cut.read_text(encoding="utf-8", errors="replace")

    results = pack / ".oracle-results"
    results.mkdir(exist_ok=True)
    output = results / f"{entry or 'suite'}.json"
    output.unlink(missing_ok=True)
    args = ["run", str(program), "--cut", str(cut), "--copybook-path", str(copybooks)]
    if kind == "baseline":
        args += ["--record-baseline", str(output)]
    else:
        args += ["--baseline", str(baseline_file), "--baseline-json", str(output)]
    step = _run_step(command, args, pack, timeout)
    log.append(f"$ mockymock run {program.relative_to(pack.resolve())}\n{step.log}")
    job_log.event(
        "run finished",
        level=(
            logging.WARNING
            if step.timed_out or step.exit_code is None
            else logging.INFO
        ),
        entry=entry,
        exit_code=step.exit_code,
        timed_out=step.timed_out or None,
        duration_ms=step.duration_ms,
        command=f"mockymock {' '.join(args[:2])}",
    )
    outcome.exit_code = step.exit_code
    outcome.log = "".join(log)
    document = _read_json(output)
    if document is None:
        outcome.error = (
            "mockymock run timed out"
            if step.timed_out
            else "mockymock run produced no "
            + ("baseline" if kind == "baseline" else "comparison")
        )
    elif kind == "baseline":
        outcome.baseline = document
    else:
        outcome.comparison = document
    return outcome


def _run_tests_suite(
    pack: Path,
    suite: dict[str, Any],
    program: Path,
    cut: Path,
    copybooks: Path,
    command: Sequence[str],
    timeout: float,
    job_log: JobLog,
    outcome: SuiteOutcome,
    log: list[str],
) -> SuiteOutcome:
    """A tests job's suite: fill the expected values when asked, then play
    the suite and keep its ``--json-report``."""
    entry = outcome.entry
    base = ["run", str(program), "--cut", str(cut), "--copybook-path", str(copybooks)]
    shown = program.relative_to(pack.resolve())
    if suite.get("record"):
        step = _run_step(command, [*base, "--record-expectations"], pack, timeout)
        log.append(f"$ mockymock run {shown} --record-expectations\n{step.log}")
        job_log.event(
            "record expectations finished",
            level=(
                logging.WARNING
                if step.timed_out or step.exit_code is None
                else logging.INFO
            ),
            entry=entry,
            exit_code=step.exit_code,
            timed_out=step.timed_out or None,
            duration_ms=step.duration_ms,
            command="mockymock run --record-expectations",
        )
        if step.timed_out or RECORDED_MARK not in step.log:
            # No recording: the suite did not compile, was refused, or hung.
            # Playing it now would report its STUB EXPECT placeholders as a
            # recording (`recorded` was set whatever the step did), and the
            # backend kept that .cut as the module's tests: every later run
            # replayed it, never filling or checking them (2026-11-05).
            outcome.exit_code = step.exit_code
            outcome.cut_text = cut.read_text(encoding="utf-8", errors="replace")
            outcome.log = "".join(log)
            outcome.error = (
                "mockymock run --record-expectations timed out"
                if step.timed_out
                else "mockymock run --record-expectations recorded nothing "
                "(the suite did not compile or run; see its log)"
            )
            return outcome
        outcome.recorded = True
    outcome.cut_text = cut.read_text(encoding="utf-8", errors="replace")

    results = pack / ".oracle-results"
    results.mkdir(exist_ok=True)
    output = results / f"{entry or 'suite'}.report.json"
    output.unlink(missing_ok=True)
    coverage = results / f"{entry or 'suite'}.coverage.json"
    coverage.unlink(missing_ok=True)
    step = _run_step(
        command,
        [*base, "--json-report", str(output), "--branch-coverage", str(coverage)],
        pack,
        timeout,
    )
    log.append(f"$ mockymock run {shown}\n{step.log}")
    job_log.event(
        "run finished",
        level=(
            logging.WARNING
            if step.timed_out or step.exit_code is None
            else logging.INFO
        ),
        entry=entry,
        exit_code=step.exit_code,
        timed_out=step.timed_out or None,
        duration_ms=step.duration_ms,
        command="mockymock run --json-report",
    )
    outcome.exit_code = step.exit_code
    outcome.log = "".join(log)
    outcome.report = _read_json(output)
    outcome.coverage = _read_json(coverage)
    named = suite_files(pack, cut, outcome.cut_text)
    if named or suite.get("level") == 2:
        outcome.files = named
    if outcome.report is None:
        outcome.error = (
            "mockymock run timed out"
            if step.timed_out
            else "mockymock run produced no report (the suite did not compile or run)"
        )
    return outcome


_FILE_PATH_RE = re.compile(
    r'^\s*(?:USE\s+REAL\s+FILE\s+\S+\s+FROM|EXPECT\s+FILE\s+\S+\s+MATCHES)\s+"([^"]+)"',
    re.IGNORECASE | re.MULTILINE,
)


def _encoded(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size > MAX_REPORTED_FILE_BYTES:
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


def suite_files(pack: Path, cut: Path, cut_text: str) -> dict[str, str]:
    """The data and golden files a level-2 ``.cut`` names (USE REAL FILE
    ... FROM, EXPECT FILE ... MATCHES) that exist, as pack-relative path ->
    base64. Paths that leave the pack are skipped."""
    root = pack.resolve()
    out: dict[str, str] = {}
    for relative in _FILE_PATH_RE.findall(cut_text):
        target = (cut.parent / relative).resolve()
        if not target.is_relative_to(root):
            continue
        encoded = _encoded(target)
        if encoded is not None:
            out[target.relative_to(root).as_posix()] = encoded
    return out


def _folder_files(pack: Path, folder: Path) -> dict[str, str]:
    root = pack.resolve()
    out: dict[str, str] = {}
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            encoded = _encoded(path)
            if encoded is not None:
                out[path.resolve().relative_to(root).as_posix()] = encoded
    return out


def run_job_unit(
    pack: Path,
    manifest: dict[str, Any],
    unit: dict[str, Any],
    command: Sequence[str] = DEFAULT_COMMAND,
    timeout: float = DEFAULT_SUITE_TIMEOUT,
    job_log: JobLog | None = None,
) -> dict[str, Any]:
    """Run one JCL job of a tests job (level 3) with ``mockymock job``;
    its outcome: the job report, the input and expected datasets (base64)
    and the log. Problems go in ``error``, never raised."""
    job_log = job_log or JobLog()
    name = str(unit.get("name") or "")
    outcome: dict[str, Any] = {"name": name, "jcl": unit.get("jcl")}
    try:
        jcl = _inside(pack, unit.get("jcl"), "job jcl")
        data = _inside(pack, unit.get("data") or f"jobs/{name}/data", "job data")
        expected = _inside(
            pack, unit.get("expected") or f"jobs/{name}/expected", "job expected"
        )
        sources = _inside(pack, manifest.get("source_path") or "src", "source_path")
        copybooks = _inside(
            pack, manifest.get("copybook_path") or "copybooks", "copybook_path"
        )
        proclib = (
            _inside(pack, manifest.get("proclib_path"), "proclib_path")
            if manifest.get("proclib_path")
            else None
        )
    except JobPackError as exc:
        outcome["error"] = str(exc)
        return outcome
    data.mkdir(parents=True, exist_ok=True)
    results = pack / ".oracle-results"
    results.mkdir(exist_ok=True)
    report_path = results / f"job-{name or 'job'}.json"
    report_path.unlink(missing_ok=True)
    args = [
        "job",
        str(jcl),
        "--src",
        str(sources),
        "--data",
        str(data),
        "--expected",
        str(expected),
        "--copybook-path",
        str(copybooks),
        "--json-report",
        str(report_path),
        "--generate-inputs",
    ]
    if proclib is not None:
        args += ["--proclib", str(proclib)]
    record = bool(unit.get("record")) or not expected.is_dir()
    if record:
        args.append("--record")
    job_log.event("job run started", job=name, record=record or None)
    step = _run_step(command, args, pack, timeout)
    job_log.event(
        "job run finished",
        level=logging.WARNING if step.exit_code not in (0, 1) else logging.INFO,
        job=name,
        exit_code=step.exit_code,
        timed_out=step.timed_out or None,
        duration_ms=step.duration_ms,
        command="mockymock job",
    )
    outcome["exit_code"] = step.exit_code
    outcome["duration_ms"] = step.duration_ms
    outcome["recorded"] = record
    outcome["log"] = step.log[-MAX_LOG_CHARS:]
    outcome["report"] = _read_json(report_path)
    outcome["files"] = {**_folder_files(pack, data), **_folder_files(pack, expected)}
    if outcome["report"] is None:
        outcome["error"] = (
            "mockymock job timed out"
            if step.timed_out
            else "mockymock job produced no report (see its log)"
        )
    return outcome


def run_pack(
    pack: Path,
    command: Sequence[str] = DEFAULT_COMMAND,
    timeout: float = DEFAULT_SUITE_TIMEOUT,
    job_log: JobLog | None = None,
) -> dict[str, Any]:
    """Run every suite of an unpacked pack; the backend's result payload.

    Raises:
        JobPackError: The manifest is unusable.
    """
    job_log = job_log or JobLog()
    manifest = load_manifest(pack)
    job_log.event(
        "manifest read",
        kind=manifest["kind"],
        load_module=manifest.get("load_module"),
        suites=len(manifest["suites"]),
    )
    outcomes = [
        run_suite(pack, manifest, suite, command, timeout, job_log)
        for suite in manifest["suites"]
    ]
    payload: dict[str, Any] = {"suites": [outcome.to_dict() for outcome in outcomes]}
    if manifest.get("jobs"):
        payload["jobs"] = [
            run_job_unit(pack, manifest, unit, command, timeout, job_log)
            for unit in manifest["jobs"]
        ]
    return payload


def run_job(
    content: bytes,
    command: Sequence[str] = DEFAULT_COMMAND,
    timeout: float = DEFAULT_SUITE_TIMEOUT,
    work_dir: Path | None = None,
    keep: bool = False,
    job_log: JobLog | None = None,
) -> dict[str, Any]:
    """Unpack and run a job's pack; the result payload, with ``error`` set
    when the whole job could not run, and ``log``: the job's timeline."""
    job_log = job_log or JobLog()
    work = Path(tempfile.mkdtemp(prefix="mockymock-oracle-", dir=work_dir))
    try:
        try:
            pack = extract_pack(content, work)
            job_log.event("pack unpacked", bytes=len(content), folder=str(work))
            payload = run_pack(pack, command, timeout, job_log)
        except JobPackError as exc:
            job_log.error("job cannot run", error=str(exc))
            payload = {"suites": [], "error": str(exc)}
    finally:
        if keep:
            job_log.event("work folder kept (--keep)", folder=str(work))
        else:
            shutil.rmtree(work, ignore_errors=True)
    failed = sum(1 for s in payload["suites"] if s.get("error"))
    job_log.event(
        "job finished",
        level=logging.WARNING if failed or payload.get("error") else logging.INFO,
        suites=len(payload["suites"]),
        failed_suites=failed,
        duration_ms=job_log.elapsed_ms(),
    )
    payload["log"] = job_log.text()
    return without_nul(payload)


def without_nul(value: Any) -> Any:
    """``value`` with every NUL character in its strings written as ``\\x00``.

    A suite's output can hold binary field values (``--record-expectations``
    prints each recorded value, LOW-VALUES included), and the backend
    refuses a request body with a NUL character, so the whole result would
    be lost (seen on ACCTUPD's VSAM record, 2026-11-02).
    """
    if isinstance(value, str):
        return value.replace("\x00", "\\x00") if "\x00" in value else value
    if isinstance(value, dict):
        return {key: without_nul(item) for key, item in value.items()}
    if isinstance(value, list):
        return [without_nul(item) for item in value]
    return value


#: Seconds between the attempts to report a result the backend could not
#: take (unreachable, restarting, a 5xx): about 8 minutes in all.
REPORT_RETRY_DELAYS: tuple[float, ...] = (5, 15, 30, 60, 120, 240)


def _transient(exc: RunnerClientError) -> bool:
    """Whether a refused request is worth sending again: the backend was not
    reached, or answered 429 or 5xx. A 4xx (job not running, bad payload)
    is final."""
    return exc.status is None or exc.status == 429 or exc.status >= 500


def _report(
    client: RunnerClient,
    job_id: str,
    payload: dict[str, Any],
    sleep: Callable[[float], None],
    logger: logging.Logger,
) -> dict[str, Any]:
    """`client.report`, retried while the failure is transient: one try lost
    the whole run when the backend restarted as the job ended, and the job
    then sat "running" until the backend's job timeout (2026-11-05)."""
    for delay in REPORT_RETRY_DELAYS:
        try:
            return client.report(job_id, payload)
        except RunnerClientError as exc:
            if not _transient(exc):
                raise
            logger.warning(
                "cannot report the result, retrying",
                extra={"job_id": job_id, "error": str(exc), "retry_in_s": delay},
            )
            sleep(delay)
    return client.report(job_id, payload)


def default_runner_name() -> str:
    return f"mockymock@{socket.gethostname()}"


def serve(
    client: RunnerClient,
    runner_name: str | None = None,
    once: bool = False,
    poll_interval: float = 10.0,
    command: Sequence[str] = DEFAULT_COMMAND,
    timeout: float = DEFAULT_SUITE_TIMEOUT,
    work_dir: Path | None = None,
    keep: bool = False,
    log: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Claim, run and report jobs until stopped.

    With ``once`` the loop ends when no job is queued and returns the
    number of jobs it ran; otherwise it waits ``poll_interval`` seconds and
    asks again. A backend that cannot be reached is retried, not fatal,
    except with ``once``, where it raises.
    """
    name = runner_name or default_runner_name()
    say: Callable[[str], None] = log or (lambda message: LOGGER.info(message))
    LOGGER.info(
        "mockymock runner started",
        extra={
            "runner": name,
            "backend": getattr(client, "base_url", None),
            **environment(),
        },
    )
    ran = 0
    while True:
        try:
            job = client.claim(name)
        except RunnerClientError as exc:
            if once or exc.status in (401, 503):
                raise
            LOGGER.warning(
                "backend unreachable, retrying",
                extra={"error": str(exc), "retry_in_s": poll_interval},
            )
            if log is not None:
                say(f"mockymock runner: {exc}; retrying in {poll_interval:.0f}s")
            sleep(poll_interval)
            continue
        if job is None:
            if once:
                return ran
            sleep(poll_interval)
            continue
        job_id = str(job["id"])
        job_log = JobLog(job_id)
        if log is not None:
            say(f"mockymock runner: job {job_id} ({job.get('kind')}) claimed")
        job_log.event(
            "job claimed",
            kind=job.get("kind"),
            load_module_id=job.get("load_module_id"),
            runner=name,
        )
        job_log.event("environment", **environment())
        try:
            started = time.monotonic()
            content = client.download_pack(job)
            job_log.event(
                "pack downloaded",
                bytes=len(content),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            payload = run_job(content, command, timeout, work_dir, keep, job_log)
        except RunnerClientError as exc:
            job_log.error("cannot download the pack", error=str(exc))
            payload = {
                "suites": [],
                "error": f"cannot download the pack: {exc}",
                "log": job_log.text(),
            }
        except Exception as exc:  # noqa: BLE001 - report it rather than die silently
            LOGGER.exception("job crashed", extra={"job_id": job_id})
            job_log.error("runner crashed while running the job", error=repr(exc))
            payload = {
                "suites": [],
                "error": f"the runner crashed: {exc!r}",
                "log": job_log.text(),
            }
        try:
            summary = _report(client, job_id, payload, sleep, LOGGER)
        except RunnerClientError as exc:
            LOGGER.error(
                "cannot report the result",
                extra={"job_id": job_id, "error": str(exc)},
            )
            if log is not None:
                say(f"mockymock runner: job {job_id}: cannot report the result: {exc}")
        else:
            LOGGER.info(
                "job reported",
                extra={
                    "job_id": job_id,
                    "status": summary.get("status"),
                    "verdict": summary.get("verdict"),
                },
            )
            if log is not None:
                say(
                    f"mockymock runner: job {job_id} {summary.get('status')}"
                    + (f", {summary['verdict']}" if summary.get("verdict") else "")
                )
        ran += 1
