# Real files (level 2) and whole-job runs (level 3): design

Date: 2026-11-06. Level 1 is [load-module integration](2026-11-01-real-call-integration-design.md).

## 2. Integration tests, level 2: real files

Level 1 runs a whole load module with every boundary that leaves it mocked. Level 2 keeps that, but sequential files are real: records are staged into the input files, the program really OPENs, READs and WRITEs them, and the output files are compared with recorded golden files.

New `.cut` statements:

```
USE REAL FILE INV-FILE FROM "data/INVUPDT/INV-FILE.dat"   *> input staged before each case
USE REAL FILE RPT-FILE                                    *> starts empty
PERFORM MAIN-PROCESS THRU ASK-CONFIRM
EXPECT FILE RPT-FILE MATCHES "expected/INVUPDT/1/RPT-FILE.dat"
SAVE FILE RPT-FILE TO "out/RPT-FILE.dat"                  *> used by level 3
```

* Every OPEN/READ/WRITE/REWRITE/CLOSE of a real file runs as written (the gate counts it as covered, `VERIFY` still counts it). The SELECT's ASSIGN is pointed at a file in the run's sandbox; nothing outside the sandbox is touched.
* Files are staged per case, so cases stay independent. Each case's output is snapshotted at the end of the case and compared after the run, record by record; a failure names the first differing record and shows both.
* `--record-expectations` writes a missing golden file from what the program produced, the same way it fills `STUB EXPECT` values.
* Sequential and line-sequential files only. Indexed (VSAM KSDS) and relative files stay mocked and are listed as such, since GnuCOBOL's indexed files are not VSAM images.

`mockymock generate --real-files` turns the scenario suite into a level-2 suite: each scenario's generated READ data becomes a real input file (encoded with the FD record layout by cobol-parser), output files become real with an `EXPECT FILE`, and the per-call `VERIFY` lines of real files are dropped.

## 3. Integration tests, level 3: a whole JCL job

`mockymock job JOB.jcl --src DIR --data DIR --expected DIR [--record]` runs a job's steps in order through one shared set of datasets:

* JCL is read by jcl-parser (through `cobolparser.jcl`), PROCs expanded.
* A COBOL step runs its program as a one-case level-2 suite: every file bound to a DD of the step is a real file staged from the job's datasets and saved back after the step; subprograms with source run for real; DB2, CICS, MQ and calls without source stay mocked with generated placeholders.
* `IEFBR14`, `IEBGENER`/`ICEGENER` (copy) and `SORT FIELDS=COPY` are emulated; `DD DUMMY`, in-stream `DD *`, `SYSOUT`, `&&` temporaries, `DISP=MOD` and concatenations are handled. A step the runner cannot run (another utility, a program without source) stops the job and is reported as a gap, never skipped silently.
* `COND=` on EXEC and `IF RC` blocks are evaluated on the steps' real return codes.
* At the end every dataset the job wrote (temporaries excluded, SYSOUT included) is compared with the recorded one; `--record` records them.

## 4. Backend and frontend wiring for levels 2 and 3

* A tests job takes a `level` (1, 2 or 3). Level 2 generates suites with `--real-files`; level 3 adds one job unit per JCL job of the module. The recorded data files and golden files are kept with the recorded suites, so later runs replay exactly the same inputs.
* The "Integration tests" dialog gets a level selector, and each run shows its level; level-3 runs show steps and dataset compares.


## Implementation notes

**Level 2.**

* DSL: `RealFile(file, source)` on `MockTestCase.real_files` (TESTCASE before its PERFORM, or BEFORE-EACH), `FileCheck(file, path, kind EXPECT|SAVE)` on `MockTestCase.file_checks`.
* `cli/checks.expand_real_files` refuses what cannot be exact (`REAL_FILE_UNKNOWN`, `REAL_FILE_ORGANIZATION`, `REAL_FILE_ALSO_MOCKED`, `REAL_FILE_MIXED_STATEMENT`, `FILE_CHECK_NOT_REAL`) and answers every site of a real file with a pass-through `MockDirective(real_file=F)`, which the injector splices like `USE REAL CALL`: the statement runs as written.
* `splicer/real_files.py`: `rewrite_assigns` points each real file's ASSIGN at `ut-files/<FILE>` in the sandbox; `insert_case_staging` deletes and re-stages the files at the start of each case (`CBL_DELETE_FILE`, `CBL_COPY_FILE`) and copies each checked file to `ut-out/<case>-<n>` at its end; `check_files` compares them after the run (fixed records split by the FD's record length, line-sequential records with trailing blanks dropped, as GnuCOBOL writes them).
* `dsl/real_file_suite.py`: `generate --real-files` drops the file MOCK blocks, VERIFY and STUB lines of real files, encodes each scenario's READ rows with the FD layout (cobol-parser's `encode_record`, other fields filled from their PICTUREs with a fixed seed) into `data/<PROG>/<case>-<FILE>.dat`, and adds `EXPECT FILE ... MATCHES "expected/<PROG>/<case>-<FILE>.dat"`, recorded by the first `run --record-expectations`.

**Level 3** (`mockymock/jobstream/`).

* `runner.py`: `mockymock job` reads the JCL with `cobolparser.jcl` (needs the `jcl` extra: `pip install 'mockymock[jcl]'`). A COBOL step is generated (`generate`, `--real` for every statically CALLed program with source), reduced to one case (`step_suite`), its files bound by ASSIGN -> DD name (`UT-S-INFILE` -> `INFILE`), and run in process; the RETURN-CODE is read back from an `EXPECT RETURN-CODE TO BE 0`. Outputs come back through `SAVE FILE`.
* `conditions.py`: `COND=` (with EVEN / ONLY) and `IF` expressions (`STEP.RC`, `RC`, `ABEND`, `STEP.ABEND`, `STEP.RUN`, NOT / AND / OR); anything else raises `ConditionError`, a gap.
* `utilities.py`: IEFBR14, IEBGENER / ICEGENER without control statements, SORT / MERGE with `FIELDS=COPY` or CH / ZD / BI keys (stable, as DFSORT EQUALS); anything else raises `UtilityGap`.
* Dispositions: DELETE removes the dataset at step end, MOD appends, `&&` temporaries never reach the compare.
* Verdict: `passed`, `failed` (a dataset differs or is missing, a step's suite failed), `recorded`, or `incomplete` (a gap, an abend). Exit codes 0 / 1 / 3.
* `--generate-inputs` writes a missing input dataset from the reading program's record layout (into `--data`), so a first run needs no data.
* Example: `examples/jobflow` (IEFBR14, a COBOL extract with DB2 mocked, a SORT, a report step, `COND=(4,LE,EXTRACT)`).

**Runner.** A tests job suite with `"level": 2` is generated with `--real-files` and reports the files its `.cut` names (`files`, base64). A tests job may list `jobs` (level 3): each runs `mockymock job --generate-inputs` (with `--record` the first time) and reports the job report and its input and expected datasets.

## Limits
 (said in the product, not hidden)

* Coverage is of what the recorded tests ran, per program; a branch can be reached and still be wrong.
* Level 2/3 data is generated from the record layouts unless the user supplies files; it exercises the code paths the scenarios aim at, not production volumes.
* No VSAM image fidelity, no real DB2/CICS/MQ.
