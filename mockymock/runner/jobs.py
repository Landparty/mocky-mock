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
  and reports the comparison.

Each mockymock command runs as a child process (``python -m mockymock``)
with a timeout, so one suite that hangs or crashes does not take the
runner down. Every path the manifest names must stay inside the pack.
"""

from __future__ import annotations

import io
import json
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

MANIFEST = "oracle.json"
MANIFEST_VERSION = 1
#: Characters of a command's output kept in a suite's log.
MAX_LOG_CHARS = 20_000
#: Seconds one `mockymock generate` or `mockymock run` may take.
DEFAULT_SUITE_TIMEOUT = 900
#: Largest pack the runner unpacks (compressed and uncompressed).
MAX_PACK_BYTES = 200 * 1024 * 1024

#: Flags of the manifest's `generate` command the runner passes on.
_GENERATE_PATH_FLAGS = {"--real"}
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
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "entry": self.entry,
            "cut_path": self.cut_path,
            "cut_text": self.cut_text,
            "exit_code": self.exit_code,
            "log": self.log[-MAX_LOG_CHARS:],
        }
        if self.baseline is not None:
            out["baseline"] = self.baseline
        if self.comparison is not None:
            out["comparison"] = self.comparison
        if self.error:
            out["error"] = self.error
        return out


@dataclass
class _Step:
    exit_code: int | None
    log: str
    timed_out: bool = False
    extra: list[str] = field(default_factory=list)


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
            destination.write_bytes(archive.read(info))
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
    if manifest.get("kind") not in ("baseline", "compare"):
        raise JobPackError(f"{MANIFEST} kind {manifest.get('kind')!r} is unknown")
    suites = manifest.get("suites")
    if not isinstance(suites, list) or not suites:
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
        if flag not in _GENERATE_PATH_FLAGS or index + 1 >= len(rest):
            raise JobPackError(f"generate argument not allowed: {flag}")
        _inside(pack, rest[index + 1], f"generate {flag}")
        args += [flag, rest[index + 1]]
        index += 2
    return args


def _run_step(
    command: Sequence[str], args: list[str], cwd: Path, timeout: float
) -> _Step:
    try:
        completed = subprocess.run(
            [*command, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        return _Step(None, output + f"\n(timed out after {timeout:.0f}s)\n", True)
    except OSError as exc:
        return _Step(None, f"cannot start {command[0]}: {exc}\n")
    return _Step(
        completed.returncode, (completed.stdout or "") + (completed.stderr or "")
    )


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
) -> SuiteOutcome:
    """Run one suite of the manifest. Problems specific to the suite are
    reported in the outcome's ``error``, never raised."""
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
        if not cut.is_file():
            outcome.exit_code = step.exit_code
            outcome.log = "".join(log)
            outcome.error = "mockymock generate did not write the .cut"
            return outcome
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


def run_pack(
    pack: Path,
    command: Sequence[str] = DEFAULT_COMMAND,
    timeout: float = DEFAULT_SUITE_TIMEOUT,
) -> dict[str, Any]:
    """Run every suite of an unpacked pack; the backend's result payload.

    Raises:
        JobPackError: The manifest is unusable.
    """
    manifest = load_manifest(pack)
    outcomes = [
        run_suite(pack, manifest, suite, command, timeout)
        for suite in manifest["suites"]
    ]
    return {"suites": [outcome.to_dict() for outcome in outcomes]}


def run_job(
    content: bytes,
    command: Sequence[str] = DEFAULT_COMMAND,
    timeout: float = DEFAULT_SUITE_TIMEOUT,
    work_dir: Path | None = None,
    keep: bool = False,
) -> dict[str, Any]:
    """Unpack and run a job's pack; the result payload, with ``error`` set
    when the whole job could not run."""
    work = Path(tempfile.mkdtemp(prefix="mockymock-oracle-", dir=work_dir))
    try:
        try:
            pack = extract_pack(content, work)
            return run_pack(pack, command, timeout)
        except JobPackError as exc:
            return {"suites": [], "error": str(exc)}
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


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
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Claim, run and report jobs until stopped.

    With ``once`` the loop ends when no job is queued and returns the
    number of jobs it ran; otherwise it waits ``poll_interval`` seconds and
    asks again. A backend that cannot be reached is retried, not fatal,
    except with ``once``, where it raises.
    """
    name = runner_name or default_runner_name()
    ran = 0
    while True:
        try:
            job = client.claim(name)
        except RunnerClientError as exc:
            if once or exc.status in (401, 503):
                raise
            log(f"mockymock runner: {exc}; retrying in {poll_interval:.0f}s")
            sleep(poll_interval)
            continue
        if job is None:
            if once:
                return ran
            sleep(poll_interval)
            continue
        job_id = str(job["id"])
        log(f"mockymock runner: job {job_id} ({job.get('kind')}) claimed")
        try:
            payload = run_job(
                client.download_pack(job), command, timeout, work_dir, keep
            )
        except RunnerClientError as exc:
            payload = {"suites": [], "error": f"cannot download the pack: {exc}"}
        try:
            summary = client.report(job_id, payload)
        except RunnerClientError as exc:
            log(f"mockymock runner: job {job_id}: cannot report the result: {exc}")
        else:
            log(
                f"mockymock runner: job {job_id} {summary.get('status')}"
                + (f", {summary['verdict']}" if summary.get("verdict") else "")
            )
        ran += 1
