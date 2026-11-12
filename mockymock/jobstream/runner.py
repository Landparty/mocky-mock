"""`mockymock job`: run a whole JCL job end to end (integration tests level 3).

docs/2026-11-06-real-files-and-job-runs-design.md. The job's steps run in
order through one shared set of datasets:

* the JCL is read by jcl-parser (through `cobolparser.jcl`), PROCs expanded;
* a COBOL step runs its program as a one-case level-2 suite
  (`mockymock run`): each sequential file the step's DDs bind is a real
  file, staged from the job's datasets and saved back after the step;
  subprograms with source in `--src` run for real (USE REAL CALL); DB2,
  CICS, MQ, IMS and calls without source stay mocked with the generated
  placeholders. The step's RETURN-CODE is read from the case;
* IEFBR14, IEBGENER / ICEGENER and simple SORTs are emulated
  (`jobstream.utilities`); DUMMY, in-stream `DD *`, SYSOUT, `&&`
  temporaries, DISP=MOD and concatenations are handled;
* `COND=` and `IF` conditions are evaluated on the real return codes
  (`jobstream.conditions`).

A step that cannot be run exactly (another utility, a program with no
source, a condition it cannot read) stops the job and is reported as a gap.

At the end every dataset the job wrote (temporaries excluded, SYSOUT
included as `SYSOUT.<step>.<dd>`) is compared with the file of that name in
`--expected`; `--record` writes them there instead.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mockymock.jobstream.conditions import ConditionError, step_runs
from mockymock.jobstream.utilities import (
    COPY_PROGRAMS,
    NOOP_PROGRAMS,
    SORT_PROGRAMS,
    UtilityGap,
    control_statements,
    line_framed,
    refit_records,
    sort_data,
)

JOB_REPORT_VERSION = 1

#: Leading ASSIGN segments that are a device or organization code, never
#: part of the DD name (`UT-S-INFILE` is DD INFILE) -- the list
#: cobol-parser's field lineage and the LegacyLens backend strip.
_ASSIGN_PREFIXES = frozenset(
    {
        "UT",
        "UR",
        "DA",
        "S",
        "AS",
        "DISK",
        "TAPE",
        "SYSDA",
        "VIO",
        "VS",
        "GS",
        "SD",
        "SQ",
    }
)
_COBOL_SUFFIXES = (".cbl", ".cob", ".CBL", ".COB", ".cobol")


@dataclass
class StepResult:
    name: str
    program: str | None
    kind: str  # cobol | utility | none
    status: str  # ran | bypassed | gap | abended | failed
    rc: int | None = None
    detail: str | None = None
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    log: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "program": self.program,
            "kind": self.kind,
            "status": self.status,
            "rc": self.rc,
            "reads": self.reads,
            "writes": self.writes,
        }
        if self.detail:
            out["detail"] = self.detail
        if self.log:
            out["log"] = self.log[-8000:]
        return out


@dataclass
class DatasetResult:
    name: str
    status: str  # same | differs | recorded | missing | new
    detail: str | None = None
    records: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "status": self.status}
        if self.detail:
            out["detail"] = self.detail
        if self.records is not None:
            out["records"] = self.records
        return out


@dataclass
class JobOptions:
    jcl: Path
    sources: list[Path]
    data: Path
    expected: Path | None = None
    copybook_paths: list[str] = field(default_factory=list)
    proc_paths: list[str] = field(default_factory=list)
    record: bool = False
    generate_inputs: bool = False
    input_rows: int = 10
    seed: int = 0
    work_dir: Path | None = None
    keep: bool = False
    timeout: int = 60
    #: The `mockymock` command line, run in-process for each COBOL step
    #: (`generate`, then `run`): a job step IS a `mockymock run`. The CLI
    #: passes its own `main`; passing it in keeps this package from
    #: importing the CLI above it (tests/unit/test_layering.py).
    command: Callable[[list[str]], int] | None = None


def ddname_of_assign(assign: str | None) -> str | None:
    """The DD name an `ASSIGN TO` names: `UT-S-INFILE` -> `INFILE`,
    `"CUSTIN"` -> `CUSTIN`; None for a path-like literal."""
    if not assign:
        return None
    text = assign.strip().strip("\"'").upper()
    if not text or any(ch in text for ch in "/\\. "):
        return None
    parts = text.split("-")
    while len(parts) > 1 and parts[0] in _ASSIGN_PREFIXES:
        parts = parts[1:]
    return "-".join(parts)


def _is_temporary(dataset: str | None) -> bool:
    return bool(dataset) and dataset.startswith("&&")  # type: ignore[union-attr]


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9.#@$+()-]", "_", name)


def _disposition(dd: Any) -> tuple[str, str, str]:
    """(status, normal, abnormal), DISP's defaults filled in."""
    raw = dd.disposition
    if isinstance(raw, list):
        parts = [str(p).upper() for p in raw]
    elif raw:
        parts = [p.strip().upper() for p in str(raw).strip("()").split(",")]
    else:
        parts = []
    status = (parts[0] if parts and parts[0] else "NEW") or "NEW"
    normal = parts[1] if len(parts) > 1 and parts[1] else ""
    abnormal = parts[2] if len(parts) > 2 and parts[2] else ""
    if not normal:
        # z/OS: DELETE for a NEW dataset, KEEP for an existing one (OLD,
        # SHR, MOD) -- and KEEP on a `&&` temporary is PASS, so a passed
        # temporary read with a bare DISP=SHR stays there for later steps.
        if status == "NEW":
            normal = "DELETE"
        else:
            normal = "PASS" if _is_temporary(dd.dataset) else "KEEP"
    return status, normal, abnormal or normal


class JobRun:
    """One run of one job."""

    def __init__(self, options: JobOptions) -> None:
        self.options = options
        self.work = Path(
            tempfile.mkdtemp(prefix="mockymock-job-", dir=options.work_dir)
        )
        self.datasets_dir = self.work / "datasets"
        self.datasets_dir.mkdir()
        self.steps_dir = self.work / "steps"
        self.steps_dir.mkdir()
        #: Dataset name (as coded, `&&` included) -> its file.
        self.datasets: dict[str, Path] = {}
        #: Datasets a step wrote (compared at the end), in first-write order.
        self.written: dict[str, None] = {}
        self.deleted: set[str] = set()
        self.rcs: dict[str, int | None] = {}
        #: Steps a condition bypassed: a COND test naming one is ignored.
        self.bypassed: set[str] = set()
        self.abended = False
        self.gaps: list[str] = []
        self.notes: list[str] = []
        self.generated_inputs: list[str] = []
        #: Dataset -> whether its records are newline-framed, when the step
        #: that last wrote it knew (absent: tell from the data).
        self.layouts: dict[str, bool] = {}
        #: Dataset -> the LRECL a DD that wrote it coded.
        self.lrecls: dict[str, int] = {}
        self._source_index = self._index_sources()

    # -- sources ---------------------------------------------------------

    def _index_sources(self) -> dict[str, Path]:
        """PROGRAM-ID (and file stem) -> source, over every --src folder."""
        index: dict[str, Path] = {}
        for folder in self.options.sources:
            paths = [folder] if folder.is_file() else sorted(folder.rglob("*"))
            for path in paths:
                if path.suffix not in _COBOL_SUFFIXES or not path.is_file():
                    continue
                index.setdefault(path.stem.upper(), path)
                program_id = _program_id(path)
                if program_id:
                    index.setdefault(program_id.upper(), path)
        return index

    def source_of(self, program: str) -> Path | None:
        return self._source_index.get(program.upper())

    # -- datasets --------------------------------------------------------

    def _load_inputs(self) -> None:
        if not self.options.data.is_dir():
            return
        for path in sorted(self.options.data.iterdir()):
            if path.is_file():
                target = self.datasets_dir / _safe(path.name)
                shutil.copyfile(path, target)
                self.datasets[path.name.upper()] = target

    def _dataset_path(self, name: str) -> Path:
        key = name.upper()
        if key not in self.datasets:
            self.datasets[key] = self.datasets_dir / _safe(key)
        return self.datasets[key]

    # -- the run ---------------------------------------------------------

    def run(self) -> dict[str, Any]:
        try:
            return self._run()
        finally:
            if not self.options.keep:
                shutil.rmtree(self.work, ignore_errors=True)

    def _run(self) -> dict[str, Any]:
        from cobolparser.jcl import parse_jcl

        text = self.options.jcl.read_text(encoding="utf-8", errors="replace")
        parsed = parse_jcl(
            text,
            filename=self.options.jcl.name,
            proc_paths=[str(p) for p in self.options.proc_paths] or None,
        )
        report: dict[str, Any] = {
            "version": JOB_REPORT_VERSION,
            "jcl": str(self.options.jcl),
            "job": None,
            "steps": [],
            "datasets": [],
            "gaps": self.gaps,
            "notes": self.notes,
        }
        if parsed.errors or not parsed.jobs:
            self.gaps.extend(
                (
                    f"JCL line {e.get('line')}: {e.get('message')}"
                    if isinstance(e, dict)
                    else str(e)
                )
                for e in parsed.errors
            )
            if not parsed.jobs:
                self.gaps.append("no JOB in the JCL")
            report["verdict"] = "incomplete"
            return report
        if parsed.unresolved:
            self.notes.extend(f"unresolved: {item}" for item in parsed.unresolved)
        job = parsed.jobs[0]
        report["job"] = job.name
        if len(parsed.jobs) > 1:
            self.notes.append(
                f"{len(parsed.jobs)} jobs in the deck: only {job.name} runs"
            )
        if self.options.command is None:
            cobol = [
                step.program
                for step in job.steps
                if step.program
                and step.program.upper()
                not in NOOP_PROGRAMS | COPY_PROGRAMS | SORT_PROGRAMS
                and self.source_of(step.program) is not None
            ]
            if cobol:
                # Before any step runs, not in the middle of the job.
                raise ValueError(
                    f"JobOptions.command is required to run COBOL step program {cobol[0]}"
                )
        self._load_inputs()
        steps: list[StepResult] = []
        stopped = False
        for step in job.steps:
            if step.program is None:
                continue  # an EXEC PROC: its expanded steps follow
            name = (step.name or f"STEP{len(steps) + 1}").upper()
            if stopped:
                steps.append(
                    StepResult(
                        name,
                        step.program,
                        "none",
                        "bypassed",
                        detail="the job stopped earlier",
                    )
                )
                continue
            try:
                runs = step_runs(
                    step.condition,
                    self.rcs,
                    self.abended,
                    bypassed=self.bypassed,
                    step=name,
                )
            except ConditionError as exc:
                self.gaps.append(f"step {name}: condition {step.condition!r}: {exc}")
                steps.append(
                    StepResult(name, step.program, "none", "gap", detail=str(exc))
                )
                stopped = True
                continue
            if not runs:
                self.bypassed.add(name)
                steps.append(
                    StepResult(
                        name,
                        step.program,
                        "none",
                        "bypassed",
                        detail=f"condition {step.condition} bypasses it",
                    )
                )
                continue
            result = self._run_step(name, step)
            steps.append(result)
            if result.status == "gap":
                self.gaps.append(f"step {name} ({step.program}): {result.detail}")
                stopped = True
            elif result.status in ("abended", "failed"):
                self.rcs[name] = None
                self.abended = True
            else:
                self.rcs[name] = result.rc
        report["steps"] = [s.to_dict() for s in steps]
        report["datasets"] = [d.to_dict() for d in self._finish()]
        if self.generated_inputs:
            report["generated_inputs"] = self.generated_inputs
        report["verdict"] = _verdict(
            steps, report["datasets"], self.gaps, self.options.record
        )
        return report

    # -- steps -------------------------------------------------------------

    def _bindings(self, name: str, step: Any) -> tuple[dict[str, list[Any]], list[str]]:
        """DD name -> its card plus concatenated members."""
        out: dict[str, list[Any]] = {}
        for dd in step.dd_statements:
            if not dd.name:
                continue
            out[dd.name.upper()] = list(dd.flatten())
        return out, []

    def _input_file(
        self, step_name: str, ddname: str, cards: list[Any], line_sequential: bool
    ) -> tuple[Path | None, str | None]:
        """The file a step reads through DD `ddname` (a concatenation is
        joined into one file), or (None, why) when it cannot be staged."""
        parts: list[bytes] = []
        names: list[str] = []
        for dd in cards:
            if dd.is_dummy:
                continue
            if dd.is_instream:
                lines = list(dd.instream_lines or [])
                if line_sequential:
                    parts.append(
                        b"".join(
                            line.rstrip().encode("latin-1") + b"\n" for line in lines
                        )
                    )
                else:
                    parts.append(
                        b"".join(
                            line[:80].ljust(80).encode("latin-1") for line in lines
                        )
                    )
                names.append("DD *")
                continue
            if dd.sysout is not None:
                return None, f"DD {ddname} is SYSOUT but the program reads it"
            if not dd.dataset:
                return None, f"DD {ddname} names no dataset"
            key = dd.dataset.upper()
            path = self.datasets.get(key)
            if path is None or not path.exists() or key in self.deleted:
                return None, f"input dataset {dd.dataset} (DD {ddname}) does not exist"
            parts.append(path.read_bytes())
            names.append(dd.dataset)
        target = self.steps_dir / f"{step_name}.{ddname}.in"
        target.write_bytes(b"".join(parts))
        return target, None

    def _apply_dispositions(self, step: Any, normal: bool) -> None:
        for dd in step.dd_statements:
            if not dd.dataset or dd.is_dummy:
                continue
            key = dd.dataset.upper()
            status, ok, failed = _disposition(dd)
            disposition = ok if normal else failed
            if disposition == "DELETE" and not _is_temporary(dd.dataset):
                path = self.datasets.get(key)
                if path is not None and path.exists():
                    path.unlink()
                self.deleted.add(key)
            elif disposition == "DELETE":
                self.deleted.add(key)

    def _run_step(self, name: str, step: Any) -> StepResult:
        program = (step.program or "").upper()
        bindings, _ = self._bindings(name, step)
        for dd in step.dd_statements:
            if dd.dataset:
                status, _, _ = _disposition(dd)
                key = dd.dataset.upper()
                if status == "NEW" and key in self.deleted:
                    self.deleted.discard(key)
        if program in NOOP_PROGRAMS:
            self._apply_dispositions(step, True)
            return StepResult(name, program, "utility", "ran", rc=0)
        if program in COPY_PROGRAMS or program in SORT_PROGRAMS:
            try:
                result = self._run_utility(name, program, step, bindings)
            except UtilityGap as exc:
                return StepResult(name, program, "utility", "gap", detail=str(exc))
            self._apply_dispositions(step, True)
            return result
        source = self.source_of(program)
        if source is None:
            return StepResult(
                name,
                program,
                "cobol",
                "gap",
                detail=f"no source for program {program} in --src, and it is not a utility the run emulates",
            )
        result = self._run_cobol(name, program, source, step, bindings)
        self._apply_dispositions(step, result.status == "ran")
        return result

    def _write_output(
        self,
        step_name: str,
        ddname: str,
        cards: list[Any],
        data: bytes,
        *,
        holds_existing: bool = False,
        line_sequential: bool | None = None,
    ) -> str | None:
        """Store what a step wrote through DD `ddname`; the dataset name (or
        None for DUMMY). `holds_existing`: `data` already starts with the
        dataset's records (the step was staged with them and opened the file
        EXTEND or I-O), so DISP=MOD does not prepend them a second time.
        `line_sequential`: how the records are framed, when the writer
        knows (the COBOL file's ORGANIZATION); None leaves it to the
        end-of-job comparison to tell from the data and the LRECL."""
        dd = cards[0]
        if dd.is_dummy:
            return None
        if dd.sysout is not None:
            key = f"SYSOUT.{step_name}.{ddname}"
        elif dd.dataset:
            key = dd.dataset.upper()
        else:
            return None
        path = self._dataset_path(key)
        status = _disposition(dd)[0] if dd.dataset else "NEW"
        if (
            status == "MOD"
            and not holds_existing
            and path.exists()
            and key not in self.deleted
        ):
            data = path.read_bytes() + data
        path.write_bytes(data)
        self.deleted.discard(key)
        self.written[key] = None
        if line_sequential is None:
            self.layouts.pop(key, None)
        else:
            self.layouts[key] = line_sequential
        if dd.record_length:
            self.lrecls[key] = dd.record_length
        return key

    def _run_utility(
        self, name: str, program: str, step: Any, bindings: dict[str, list[Any]]
    ) -> StepResult:
        if program in COPY_PROGRAMS:
            source_dd, target_dd = "SYSUT1", "SYSUT2"
            sysin = bindings.get("SYSIN")
            if sysin and any(
                not dd.is_dummy and (dd.instream_lines or dd.dataset) for dd in sysin
            ):
                lines = [text for dd in sysin for text in (dd.instream_lines or [])]
                if any(text.strip() for text in lines) or any(
                    dd.dataset for dd in sysin
                ):
                    raise UtilityGap(
                        "IEBGENER with SYSIN control statements is not emulated"
                    )
        else:
            source_dd, target_dd = "SORTIN", "SORTOUT"
        if source_dd not in bindings or target_dd not in bindings:
            raise UtilityGap(f"{program} needs DD {source_dd} and DD {target_dd}")
        source, why = self._input_file(name, source_dd, bindings[source_dd], False)
        if source is None:
            raise UtilityGap(why or f"cannot stage DD {source_dd}")
        data = source.read_bytes()
        if program in SORT_PROGRAMS:
            sysin = bindings.get("SYSIN") or []
            lines = [line for dd in sysin for line in (dd.instream_lines or [])]
            if any(dd.dataset for dd in sysin):
                raise UtilityGap(
                    "SORT control statements in a dataset are not emulated"
                )
            in_lrecl = self._sortin_lrecl(bindings[source_dd])
            out_lrecl = next(
                (dd.record_length for dd in bindings[target_dd] if dd.record_length),
                None,
            )
            # SORTIN's records are split by SORTIN's own length, then fitted
            # to SORTOUT's (DFSORT's PAD=RC0 / TRUNC=RC0 defaults), not
            # re-split by SORTOUT's LRECL (#460).
            data = sort_data(data, control_statements(lines), in_lrecl or out_lrecl)
            if in_lrecl and out_lrecl and in_lrecl != out_lrecl:
                data = refit_records(data, in_lrecl, out_lrecl)
        reads = [dd.dataset for dd in bindings[source_dd] if dd.dataset]
        # A copy or a sort keeps its input's framing.
        layouts = {
            self.layouts.get(dd.dataset.upper()) if dd.dataset else False
            for dd in bindings[source_dd]
            if not dd.is_dummy
        }
        written = self._write_output(
            name,
            target_dd,
            bindings[target_dd],
            data,
            line_sequential=layouts.pop() if len(layouts) == 1 else None,
        )
        return StepResult(
            name,
            program,
            "utility",
            "ran",
            rc=0,
            reads=reads,
            writes=[written] if written else [],
        )

    def _sortin_lrecl(self, dds: list[Any]) -> int | None:
        """SORTIN's record length: coded on a DD, recorded for its dataset
        by an earlier step, or 80 for in-stream card images (#460)."""
        for dd in dds:
            if dd.record_length:
                return int(dd.record_length)
        for dd in dds:
            if dd.dataset and dd.dataset.upper() in self.lrecls:
                return self.lrecls[dd.dataset.upper()]
        staged = [dd for dd in dds if not dd.is_dummy]
        if staged and all(dd.is_instream for dd in staged):
            # In-stream data is always 80-byte card images.
            return 80
        return None

    # -- COBOL steps -------------------------------------------------------

    def _run_cobol(
        self,
        name: str,
        program: str,
        source: Path,
        step: Any,
        bindings: dict[str, list[Any]],
    ) -> StepResult:
        mockymock = self.options.command
        if mockymock is None:
            raise ValueError("JobOptions.command is required to run a COBOL step")

        step_dir = self.steps_dir / name
        step_dir.mkdir(parents=True, exist_ok=True)
        cut = step_dir / f"{program}.cut"
        log = io.StringIO()
        reals = self._real_subprograms(source)
        generate = [
            "generate",
            str(source),
            "-o",
            str(cut),
            "--force",
            "--seed",
            str(self.options.seed),
        ]
        for path in self.options.copybook_paths:
            generate += ["--copybook-path", str(path)]
        for real in reals:
            generate += ["--real", str(real)]
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            code = _quiet(mockymock, generate)
        if code != 0 or not cut.is_file():
            return StepResult(
                name,
                program,
                "cobol",
                "gap",
                detail="mockymock generate could not scaffold the step's suite",
                log=log.getvalue(),
            )
        files, problem = self._step_files(name, source, bindings)
        if problem is not None:
            return StepResult(
                name, program, "cobol", "gap", detail=problem, log=log.getvalue()
            )
        text = step_suite(cut.read_text(encoding="utf-8"), files, name)
        cut.write_text(text, encoding="utf-8")
        report_path = step_dir / "report.json"
        run = [
            "run",
            str(source),
            "--cut",
            str(cut),
            "--json-report",
            str(report_path),
            "--timeout",
            str(self.options.timeout),
        ]
        for path in self.options.copybook_paths:
            run += ["--copybook-path", str(path)]
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            _quiet(mockymock, run)
        result = StepResult(name, program, "cobol", "ran", log=log.getvalue())
        result.reads = sorted(
            {dd.dataset for f in files if f.reads for dd in f.cards if dd.dataset}
        )
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result.status = "gap"
            result.detail = (
                "the step's suite did not run (refused or did not compile; see its log)"
            )
            return result
        cases = report.get("cases") or []
        if not cases:
            result.status = "gap"
            result.detail = "the step's suite has no case"
            return result
        case = cases[0]
        status = case.get("status")
        if status == "crashed":
            result.status = "abended"
            result.detail = str(
                case.get("crashDetail") or "the program ended abnormally"
            )
            return result
        result.rc = _return_code(case)
        unexpected = [
            f.get("message")
            for f in case.get("failures") or []
            if "RETURN-CODE" not in str(f.get("message") or "")
        ]
        if unexpected:
            result.status = "failed"
            result.detail = "; ".join(str(m) for m in unexpected)[:500]
            return result
        for spec in files:
            if not spec.writes:
                continue
            saved = step_dir / "out" / spec.file
            if saved.exists():
                key = self._write_output(
                    name,
                    spec.ddname,
                    spec.cards,
                    saved.read_bytes(),
                    holds_existing=spec.holds_existing,
                    line_sequential=spec.line_sequential,
                )
                if key:
                    result.writes.append(key)
        return result

    def _real_subprograms(self, source: Path) -> list[Path]:
        """Sources of the programs `source` CALLs statically that --src
        holds (they run for real), transitively."""
        found: dict[str, Path] = {}
        pending = [source]
        while pending:
            current = pending.pop()
            for target in _static_calls(current):
                path = self.source_of(target)
                if path is None or path == source or target in found:
                    continue
                found[target] = path
                pending.append(path)
        return list(found.values())

    def _step_files(
        self, name: str, source: Path, bindings: dict[str, list[Any]]
    ) -> tuple[list[StepFile], str | None]:
        """The step's real files: every sequential file whose ASSIGN names a
        DD of the step, its input staged."""
        from cobolparser import parse_cobol

        from mockymock.analysis.mock_surface import analyze
        from mockymock.dsl.real_file_suite import plan_real_files

        text = source.read_text(encoding="utf-8", errors="replace")
        expanded = _expanded(text, source, self.options.copybook_paths)
        ast = parse_cobol(expanded, filename=source.name).ast
        if ast is None:
            return [], f"step {name}: {source.name} does not parse"
        plans, _ = plan_real_files(ast, analyze(ast))
        assigns = _assigns(ast)
        files: list[StepFile] = []
        for plan in plans:
            ddname = ddname_of_assign(assigns.get(plan.file))
            if ddname is None or ddname not in bindings:
                self.notes.append(
                    f"step {name}: {plan.file} (ASSIGN {assigns.get(plan.file)}) has no DD in the step and stays mocked"
                )
                continue
            cards = bindings[ddname]
            spec = StepFile(
                plan.file,
                ddname,
                cards,
                plan.reads,
                plan.writes,
                names=set(plan.names),
                opens_existing=plan.opens_existing,
                opens_output=plan.opens_output,
                line_sequential=plan.line_sequential,
            )
            # OPEN EXTEND appends after the records already there, whatever
            # the DISP, and OPEN I-O rewrites them: both start from the
            # dataset's current contents, READ or not.
            if plan.reads or plan.opens_existing:
                staged, why = self._input_file(
                    name, ddname, cards, plan.line_sequential
                )
                # Only a file the program reads gets generated records: an
                # EXTEND / I-O file with no dataset yet starts empty.
                can_generate = (
                    plan.reads
                    and self.options.generate_inputs
                    and len(cards) == 1
                    and bool(cards[0].dataset)
                    and not _is_temporary(cards[0].dataset)
                )
                if staged is None and can_generate:
                    staged = self._generate_input(cards[0].dataset, plan)
                    why = None
                if staged is None and not plan.writes:
                    return [], why
                # An I-O / EXTEND file with no dataset yet starts empty.
                spec.source = staged
            files.append(spec)
        return files, None

    def _generate_input(self, dataset: str, plan: Any) -> Path:
        from mockymock.dsl.real_file_suite import encode_rows

        data = encode_rows(
            plan, [{} for _ in range(self.options.input_rows)], self.options.seed
        )
        self.options.data.mkdir(parents=True, exist_ok=True)
        (self.options.data / dataset).write_bytes(data)
        target = self._dataset_path(dataset)
        target.write_bytes(data)
        self.generated_inputs.append(dataset)
        return target

    # -- the end ------------------------------------------------------------

    def _finish(self) -> list[DatasetResult]:
        results: list[DatasetResult] = []
        expected = self.options.expected
        for key in self.written:
            if _is_temporary(key) or key in self.deleted:
                continue
            path = self.datasets.get(key)
            if path is None or not path.exists():
                continue
            data = path.read_bytes()
            if expected is None:
                results.append(DatasetResult(key, "new"))
                continue
            golden = expected / key
            if self.options.record:
                expected.mkdir(parents=True, exist_ok=True)
                golden.write_bytes(data)
                results.append(DatasetResult(key, "recorded"))
                continue
            if not golden.is_file():
                results.append(
                    DatasetResult(
                        key,
                        "missing",
                        detail=f"no expected file {golden.name} (run with --record)",
                    )
                )
                continue
            from mockymock.splicer.real_files import FileLayout, compare_file

            difference = compare_file(
                data,
                golden.read_bytes(),
                (
                    FileLayout("LINE SEQUENTIAL", None)
                    if self.layouts.get(key, line_framed(data, self.lrecls.get(key)))
                    else FileLayout("SEQUENTIAL", self.lrecls.get(key))
                ),
            )
            results.append(
                DatasetResult(
                    key, "same" if difference is None else "differs", detail=difference
                )
            )
        if expected is not None and expected.is_dir() and not self.options.record:
            produced = {r.name for r in results}
            for golden in sorted(expected.iterdir()):
                if golden.is_file() and golden.name.upper() not in produced:
                    results.append(
                        DatasetResult(
                            golden.name,
                            "missing",
                            detail="the job did not write it this time",
                        )
                    )
        return results


@dataclass
class StepFile:
    file: str
    ddname: str
    cards: list[Any]
    reads: bool
    writes: bool
    source: Path | None = None
    #: The file and its record names (upper case): the MOCK keys to drop.
    names: set[str] = field(default_factory=set)
    #: Opened EXTEND or I-O: what the step saves already holds the staged
    #: records, so DISP=MOD must not prepend them again.
    opens_existing: bool = False
    #: Also opened OUTPUT, which truncates the staged records: under
    #: DISP=MOD (where OPEN OUTPUT appends on z/OS) they are prepended again.
    opens_output: bool = False
    #: The program's ORGANIZATION is LINE SEQUENTIAL.
    line_sequential: bool = False

    @property
    def holds_existing(self) -> bool:
        """What the step saves already starts with the dataset's records."""
        return self.opens_existing and not self.opens_output and self.source is not None


def step_suite(cut_text: str, files: list[StepFile], step: str) -> str:
    """The generated suite reduced to the step's run: its first case, the
    mocks of its non-file boundaries kept, every real file declared, the
    outputs saved, and the RETURN-CODE read back through an EXPECT."""
    from mockymock.dsl.real_file_suite import _END_MOCK_RE, _MOCK_RE, _TESTCASE_RE

    names = {name for f in files for name in (f.names or {f.file})}

    out: list[str] = []
    in_case = 0
    skipping = False
    in_mock = False
    perform_seen = False
    for line in cut_text.split("\n"):
        stripped = line.strip()
        if in_mock:
            if _END_MOCK_RE.match(stripped):
                in_mock = False
                if skipping:
                    skipping = False
                    continue
            if not skipping and in_case <= 1:
                out.append(line)
            continue
        if _TESTCASE_RE.match(stripped):
            in_case += 1
            if in_case > 1:
                continue
            out.append(f'TESTCASE "step {step}"')
            continue
        if in_case > 1:
            continue
        match = _MOCK_RE.match(stripped)
        if match is not None:
            in_mock = True
            key = match.group("key").upper()
            skipping = key in names
            if skipping:
                continue
            out.append(line)
            continue
        if stripped.startswith("MOCK "):
            in_mock = True
            out.append(line)
            continue
        if stripped.upper().startswith(("VERIFY", "EXPECT", "*> STUB", "*> VERIFY")):
            continue
        if (
            stripped.upper().startswith("PERFORM ")
            and in_case == 1
            and not perform_seen
        ):
            perform_seen = True
            for spec in files:
                if spec.source is not None:
                    out.append(
                        f'    USE REAL FILE {spec.file} FROM "{spec.source.as_posix()}"'
                    )
                else:
                    out.append(f"    USE REAL FILE {spec.file}")
            out.append(line)
            out.append("    EXPECT RETURN-CODE TO BE 0")
            for spec in files:
                if spec.writes:
                    out.append(f'    SAVE FILE {spec.file} TO "out/{spec.file}"')
            continue
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def _return_code(case: dict[str, Any]) -> int:
    for failure in case.get("failures") or []:
        if "RETURN-CODE" in str(failure.get("message") or ""):
            actual = str(failure.get("actual") or "")
            digits = re.sub(r"[^0-9-]", "", actual)
            try:
                return int(digits) if digits not in ("", "-") else 0
            except ValueError:
                return 0
    return 0


def _quiet(command: Any, argv: list[str]) -> int:
    try:
        return int(command(argv) or 0)
    except SystemExit as exc:  # argparse
        return int(exc.code or 0) if isinstance(exc.code, int) else 2


def _program_id(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(
        r"PROGRAM-ID\.?\s+['\"]?([A-Za-z0-9][A-Za-z0-9-]*)", text, re.IGNORECASE
    )
    return match.group(1).upper() if match else None


def _static_calls(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = [
        line[6:72]
        for line in text.splitlines()
        if len(line) > 6 and line[6] not in "*/"
    ]
    body = "\n".join(lines)
    return sorted(
        {
            m.upper()
            for m in re.findall(
                r"\bCALL\s+['\"]([A-Za-z0-9][A-Za-z0-9-]*)['\"]", body, re.IGNORECASE
            )
        }
    )


def _expanded(text: str, source: Path, copybook_paths: list[str]) -> str:
    if not re.search(r"\bCOPY\b", text, re.IGNORECASE):
        return text
    try:
        from cobolparser.preprocess import expand_copybooks

        paths = [str(p) for p in copybook_paths] or [str(source.parent)]
        expansion = expand_copybooks(text, copybook_paths=paths)
        expanded = getattr(expansion, "expanded_source", None)
        if expanded is None and isinstance(expansion, tuple):
            expanded = expansion[0]
        return str(expanded or text)
    except Exception:  # noqa: BLE001 - the parse below reports what is missing
        return text


def _assigns(ast: Any) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    environment = getattr(ast, "environment_division", None)
    if environment is None:
        return out
    for select in environment.find_all_by_type("SelectStatement"):
        name = str(getattr(select, "file_name", "") or "").upper()
        if name:
            out[name] = getattr(select, "assign_to", None)
    return out


def _verdict(
    steps: list[StepResult],
    datasets: list[dict[str, Any]],
    gaps: list[str],
    record: bool,
) -> str:
    if gaps or any(s.status in ("gap", "abended") for s in steps):
        return "incomplete"
    if any(s.status == "failed" for s in steps):
        return "failed"
    if record:
        return "recorded"
    if any(d["status"] in ("differs", "missing") for d in datasets):
        return "failed"
    if any(d["status"] == "new" for d in datasets):
        return "incomplete"
    return "passed"


def run_job_stream(options: JobOptions) -> dict[str, Any]:
    """Run the job; its report (see the module docstring)."""
    return JobRun(options).run()


def format_job_console(report: dict[str, Any]) -> str:
    lines = [
        f"JOB {report.get('job') or '?'} ({report.get('jcl')}): {report.get('verdict')}"
    ]
    for step in report.get("steps", []):
        rc = "" if step.get("rc") is None else f" RC={step['rc']}"
        detail = f" -- {step['detail']}" if step.get("detail") else ""
        lines.append(
            f"  step {step['name']:<8} {str(step.get('program') or ''):<9} {step['status']}{rc}{detail}"
        )
    for dataset in report.get("datasets", []):
        detail = f" -- {dataset['detail']}" if dataset.get("detail") else ""
        lines.append(f"  dataset {dataset['name']}: {dataset['status']}{detail}")
    for gap in report.get("gaps", []):
        lines.append(f"  gap: {gap}")
    for note in report.get("notes", []):
        lines.append(f"  note: {note}")
    for generated in report.get("generated_inputs", []):
        lines.append(f"  generated input dataset: {generated}")
    return "\n".join(lines)
