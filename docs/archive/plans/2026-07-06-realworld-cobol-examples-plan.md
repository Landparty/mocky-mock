# Real-World COBOL E2E Examples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two real-world COBOL programs (DEPTMQP, DEPTMQC — a stateful
MQ producer and a mixed MQ+DB2 consumer, both adapted from the sibling
`legacy-application` banking corpus) as polished, GnuCOBOL-verified worked
examples under `examples/real-world/`, proving mockymock against
production-shaped complexity beyond the existing teaching examples
(INVUPDT, ORDRPROC).

**Architecture:** Each example is a self-contained directory (`.cbl` +
`copybooks/` + `.cut` + `README.md`) mirroring the existing
`examples/invupdt/` / `examples/ordrproc/` convention, driven by
`mockymock run <PROGRAM>.cbl --cut <PROGRAM>.cut --copybook-path
copybooks`, proven end-to-end via a dedicated `tests/integration/` file per
example (same shape as `test_invupdt_example.py`). All `.cut` content and
required source trims in this plan were already spiked and verified to
compile and pass against the real GnuCOBOL toolchain — this plan reproduces
proven content, not new design.

**Tech Stack:** Python 3.11+, pytest, mockymock CLI, Docker + GnuCOBOL
(`mockymock-cobc` container), cobolparser (sibling dependency).

## Global Constraints

- Every `mockymock run` invocation in a test MUST pass `--copybook-path
  <example-dir>/copybooks` — both examples use `COPY` statements.
- Docker must be running for integration tests to execute; they self-skip
  via `@requires_docker` (`tests/integration/_docker.py`) otherwise. Verify
  each task's tests actually ran (not skipped) before checking it off —
  `pytest -v` output will say `SKIPPED` if Docker wasn't reachable.
- Source programs are copied from `../legacy-application/cobol/*.cbl` and
  `../legacy-application/copybook/*.cpy` (sibling repo, relative to this
  repo's root) — verify that path exists on the machine running this plan
  before Task 1; if the sibling repo isn't checked out at that path, stop
  and ask rather than guessing an alternate path.
- Do not modify `mockymock/` (the engine) as part of this plan — the two
  gaps found while designing this (cobol-parser AST gap, `sqlca.py`
  DECLARE CURSOR support) are explicitly out of scope, already filed as
  separate follow-ups. If any test in this plan fails in a way that looks
  like an engine bug rather than a mistake in this plan's own fixture/test
  content, stop and report rather than patching `mockymock/`.
- COBOL `.cut` mock bodies must use bare literal values (`MOVE 2 TO
  MQ-COMP-CODE`), never named MQ-constant fields (`MOVE MQCC-FAILED TO
  MQ-COMP-CODE`), for any non-zero value — `reset.py`'s WORKING-STORAGE
  reset zero-fills named constants between test cases (see design doc's
  "Structure" section). This is already correctly done in every `.cut`
  body given in this plan; if extending these suites later, keep following
  it.

---

## Task 1: DEPTMQP example (MQ deposit producer)

**Files:**
- Create: `examples/real-world/DEPTMQP/DEPTMQP.cbl` (copied verbatim)
- Create: `examples/real-world/DEPTMQP/copybooks/WSCOMMON.cpy` (copied verbatim)
- Create: `examples/real-world/DEPTMQP/copybooks/ERRORCD.cpy` (copied verbatim)
- Create: `examples/real-world/DEPTMQP/copybooks/MQMSG.cpy` (copied, then one line re-wrapped)
- Create: `examples/real-world/DEPTMQP/DEPTMQP.cut`
- Create: `tests/integration/test_realworld_deptmqp_example.py`

**Interfaces:**
- Produces: `examples/real-world/DEPTMQP/{DEPTMQP.cbl,DEPTMQP.cut,copybooks/}`
  — Task 3 (READMEs) and Task 4 (docs) reference this exact path and the
  boundary/paragraph names used in `DEPTMQP.cut` (`1000-INITIALIZE`,
  `2000-PROCESS-DEPOSITS`, `MQCONN`/`MQOPEN`/`MQPUT`/`MQCMIT`).

- [ ] **Step 1: Copy the source program and copybooks verbatim**

```bash
mkdir -p examples/real-world/DEPTMQP/copybooks
cp ../legacy-application/cobol/DEPTMQP.cbl examples/real-world/DEPTMQP/DEPTMQP.cbl
cp ../legacy-application/copybook/WSCOMMON.cpy examples/real-world/DEPTMQP/copybooks/WSCOMMON.cpy
cp ../legacy-application/copybook/ERRORCD.cpy examples/real-world/DEPTMQP/copybooks/ERRORCD.cpy
cp ../legacy-application/copybook/MQMSG.cpy examples/real-world/DEPTMQP/copybooks/MQMSG.cpy
```

`DEPTMQP.cbl` itself needs **no edits** — its two column-72-overflow lines
(138, 156) are both `*`-comment continuations; harmless when cobolparser's
`normalize_fixed_format` truncates columns 73+ (verified empirically: the
unmodified file compiles and runs correctly through the full pipeline).

- [ ] **Step 2: Fix the one real column-72 overflow in MQMSG.cpy**

`MQ-QUEUE-NAME`'s declaration is 73 characters — its terminating period
lands in column 73 (the identification area) and is silently dropped by
`normalize_fixed_format`, which cascades into a real compile failure
(verified: `syntax error, unexpected Identifier` on the next data item).
Re-wrap it onto two lines using the Edit tool on
`examples/real-world/DEPTMQP/copybooks/MQMSG.cpy`:

Find:
```
           05  MQ-QUEUE-NAME        PIC X(48) VALUE 'BANK.DEPOSIT.QUEUE'.
```

Replace with:
```
           05  MQ-QUEUE-NAME        PIC X(48)
                                     VALUE 'BANK.DEPOSIT.QUEUE'.
```

(MQMSG.cpy's other two overflow lines — 9 and 70 — are both `*`-comments;
leave them as-is, no fix needed.)

- [ ] **Step 3: Write `examples/real-world/DEPTMQP/DEPTMQP.cut`**

This exact content was spiked and verified to produce `4 run, 0 failed`
against the real GnuCOBOL toolchain.

```
TESTSUITE "DEPTMQP deposit producer"

*> Happy path: MQCONN and MQOPEN both succeed, and the first DEPTIN
*> record is primed by the mocked READ.
TESTCASE "1000-INITIALIZE connects to MQ, opens files, and primes the first read"
    MOCK OPEN DEPTIN
    END-MOCK
    MOCK OPEN MQPRPT
    END-MOCK
    MOCK WRITE RPT-RECORD
    END-MOCK
    MOCK CALL "MQCONN"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOCK CALL "MQOPEN"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOCK READ DEPTIN
        MOVE "CIF0000001" TO BATCH-CIF-NUMBER
        MOVE "ACCT00000001" TO BATCH-ACCT-NUMBER
        MOVE "100.00" TO BATCH-AMOUNT-CHAR
        MOVE "DP" TO BATCH-TRAN-TYPE
    END-MOCK
    PERFORM 1000-INITIALIZE
    EXPECT WS-MQ-CONNECTED TO BE "Y"
    EXPECT WS-MQ-OPEN TO BE "Y"
    VERIFY CALL "MQCONN" WAS CALLED ONCE
    VERIFY CALL "MQOPEN" WAS CALLED ONCE
    VERIFY READ DEPTIN WAS PERFORMED ONCE

*> Error path: MQCONN fails, so the queue must never be opened -- proves
*> the "IF MQ-CONNECTED PERFORM 1200-MQ-OPEN" guard, not just that MQOPEN
*> is statically reachable (it still needs a mock either way).
TESTCASE "1000-INITIALIZE reports MQCONN failure without opening the queue"
    MOCK OPEN DEPTIN
    END-MOCK
    MOCK OPEN MQPRPT
    END-MOCK
    MOCK WRITE RPT-RECORD
    END-MOCK
    MOCK CALL "MQCONN"
        MOVE 2 TO MQ-COMP-CODE
        MOVE 2059 TO MQ-REASON-CODE
    END-MOCK
    MOCK CALL "MQOPEN"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOCK READ DEPTIN
        SET WS-EOF TO TRUE
    END-MOCK
    PERFORM 1000-INITIALIZE
    EXPECT WS-MQ-ERRORS TO BE 1
    VERIFY CALL "MQCONN" WAS CALLED ONCE
    VERIFY CALL "MQOPEN" WAS CALLED NEVER

*> Happy path: a valid deposit record is posted through the mocked MQPUT.
TESTCASE "2000-PROCESS-DEPOSITS posts a valid deposit through MQ"
    MOCK READ DEPTIN
        SET WS-EOF TO TRUE
    END-MOCK
    MOCK CALL "MQPUT"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOCK CALL "MQCMIT"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOCK WRITE RPT-RECORD
    END-MOCK
    MOVE "CIF0000002" TO BATCH-CIF-NUMBER
    MOVE "ACCT00000002" TO BATCH-ACCT-NUMBER
    MOVE "250.00" TO BATCH-AMOUNT-CHAR
    MOVE "DP" TO BATCH-TRAN-TYPE
    PERFORM 2000-PROCESS-DEPOSITS
    EXPECT WS-MSGS-PUT TO BE 1
    EXPECT WS-INVALID-INPUT TO BE 0
    VERIFY CALL "MQPUT" WAS CALLED ONCE
    VERIFY CALL "MQCMIT" WAS CALLED NEVER

*> Error path: a blank CIF fails validation before MQPUT is ever reached --
*> MQPUT/MQCMIT still need mocks (statically reachable) but must never fire.
TESTCASE "2000-PROCESS-DEPOSITS rejects an invalid CIF without touching MQ"
    MOCK READ DEPTIN
        SET WS-EOF TO TRUE
    END-MOCK
    MOCK CALL "MQPUT"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOCK CALL "MQCMIT"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOCK WRITE RPT-RECORD
    END-MOCK
    MOVE SPACES TO BATCH-CIF-NUMBER
    MOVE "ACCT00000003" TO BATCH-ACCT-NUMBER
    MOVE "50.00" TO BATCH-AMOUNT-CHAR
    MOVE "DP" TO BATCH-TRAN-TYPE
    PERFORM 2000-PROCESS-DEPOSITS
    EXPECT WS-INVALID-INPUT TO BE 1
    EXPECT WS-MSGS-PUT TO BE 0
    VERIFY CALL "MQPUT" WAS CALLED NEVER
```

- [ ] **Step 4: Write `tests/integration/test_realworld_deptmqp_example.py`**

```python
"""End-to-end proof for the real-world DEPTMQP (MQ deposit producer)
example -- a stateful MQCONN/MQOPEN/MQPUT/MQCMIT/MQCLOSE/MQDISC CALL
sequence plus sequential file I/O, adapted from the sibling
legacy-application repo's banking batch corpus and compiled with GnuCOBOL
in the mockymock-cobc container."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "real-world" / "DEPTMQP"
)


@requires_docker
def test_committed_deptmqp_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTMQP.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "DEPTMQP.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_deptmqp_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "DEPTMQP.cut").read_text()
    broken = tmp_path / "DEPTMQP.cut"
    broken.write_text(
        cut.replace("EXPECT WS-MSGS-PUT TO BE 1", "EXPECT WS-MSGS-PUT TO BE 2")
    )
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTMQP.cbl"),
            "--cut",
            str(broken),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 1
```

- [ ] **Step 5: Run the new tests and confirm they pass (not skipped)**

Run: `python -m pytest tests/integration/test_realworld_deptmqp_example.py -v`

Expected: both tests `PASSED` (not `SKIPPED` — if skipped, Docker isn't
reachable; start Docker Desktop and re-run before proceeding). If either
test fails, do not modify `mockymock/` — re-check the `.cut` content above
was copied exactly (whitespace-for-whitespace) and that Step 2's copybook
edit was applied; this exact content is already proven to pass.

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `python -m pytest tests/ -v`

Expected: all previously-passing tests still pass, plus the 2 new ones.

- [ ] **Step 7: Commit**

```bash
git add examples/real-world/DEPTMQP tests/integration/test_realworld_deptmqp_example.py
git commit -m "test: add real-world DEPTMQP (MQ deposit producer) e2e example"
```

---

## Task 2: DEPTMQC example (MQ deposit consumer + DB2 insert)

**Files:**
- Create: `examples/real-world/DEPTMQC/DEPTMQC.cbl` (copied verbatim)
- Create: `examples/real-world/DEPTMQC/copybooks/WSCOMMON.cpy` (copied verbatim)
- Create: `examples/real-world/DEPTMQC/copybooks/ERRORCD.cpy` (copied verbatim)
- Create: `examples/real-world/DEPTMQC/copybooks/MQMSG.cpy` (copied, same re-wrap as Task 1)
- Create: `examples/real-world/DEPTMQC/DEPTMQC.cut`
- Create: `tests/integration/test_realworld_deptmqc_example.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent example; copybooks are
  independently copied, not shared/symlinked, per the design's
  self-contained-directory convention).
- Produces: `examples/real-world/DEPTMQC/{DEPTMQC.cbl,DEPTMQC.cut,copybooks/}`
  — Task 3 and Task 4 reference this path and `DEPTMQC.cut`'s paragraph
  names (`1000-INITIALIZE`, `2300-DB2-INSERT`) and boundary keys
  (`MQCONN`/`MQOPEN`/`MQBACK`, `INSERT INTO BANK. TRANSACTION_HIST`).

- [ ] **Step 1: Copy the source program and copybooks verbatim**

```bash
mkdir -p examples/real-world/DEPTMQC/copybooks
cp ../legacy-application/cobol/DEPTMQC.cbl examples/real-world/DEPTMQC/DEPTMQC.cbl
cp ../legacy-application/copybook/WSCOMMON.cpy examples/real-world/DEPTMQC/copybooks/WSCOMMON.cpy
cp ../legacy-application/copybook/ERRORCD.cpy examples/real-world/DEPTMQC/copybooks/ERRORCD.cpy
cp ../legacy-application/copybook/MQMSG.cpy examples/real-world/DEPTMQC/copybooks/MQMSG.cpy
```

`DEPTMQC.cbl` itself needs **no edits** — its three column-72-overflow
lines (236, 305, 306) are all `*`-comment continuations, harmless
(verified empirically: the unmodified file compiles and runs correctly).

- [ ] **Step 2: Apply the same MQMSG.cpy fix as Task 1**

Edit `examples/real-world/DEPTMQC/copybooks/MQMSG.cpy`:

Find:
```
           05  MQ-QUEUE-NAME        PIC X(48) VALUE 'BANK.DEPOSIT.QUEUE'.
```

Replace with:
```
           05  MQ-QUEUE-NAME        PIC X(48)
                                     VALUE 'BANK.DEPOSIT.QUEUE'.
```

- [ ] **Step 3: Write `examples/real-world/DEPTMQC/DEPTMQC.cut`**

This exact content was spiked and verified to produce `4 run, 0 failed`
against the real GnuCOBOL toolchain. Note the space after the period in
`"INSERT INTO BANK. TRANSACTION_HIST"` — this is required, not a typo:
cobolparser's lexer tokenizes `BANK.TRANSACTION_HIST` as `BANK` `.`
`TRANSACTION_HIST`, and mockymock's SQL-prefix match text re-joins tokens
with single spaces, so the key must match that shape exactly.

```
TESTSUITE "DEPTMQC deposit consumer"

*> Happy path: MQCONN and MQOPEN both succeed.
TESTCASE "1000-INITIALIZE connects to MQ and opens the queue"
    MOCK OPEN MQCRPT
    END-MOCK
    MOCK WRITE RPT-RECORD
    END-MOCK
    MOCK CALL "MQCONN"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOCK CALL "MQOPEN"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    PERFORM 1000-INITIALIZE
    EXPECT WS-MQ-CONNECTED TO BE "Y"
    EXPECT WS-MQ-OPEN TO BE "Y"
    VERIFY CALL "MQCONN" WAS CALLED ONCE
    VERIFY CALL "MQOPEN" WAS CALLED ONCE

*> Error path: MQCONN fails, so the queue must never be opened.
TESTCASE "1000-INITIALIZE reports MQCONN failure without opening the queue"
    MOCK OPEN MQCRPT
    END-MOCK
    MOCK WRITE RPT-RECORD
    END-MOCK
    MOCK CALL "MQCONN"
        MOVE 2 TO MQ-COMP-CODE
        MOVE 2059 TO MQ-REASON-CODE
    END-MOCK
    MOCK CALL "MQOPEN"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    PERFORM 1000-INITIALIZE
    EXPECT WS-MQ-ERRORS TO BE 1
    VERIFY CALL "MQCONN" WAS CALLED ONCE
    VERIFY CALL "MQOPEN" WAS CALLED NEVER

*> Happy path: a valid deposit payload posts to DB2.
TESTCASE "2300-DB2-INSERT posts a valid deposit payload"
    MOCK SQL "INSERT INTO BANK. TRANSACTION_HIST"
        MOVE 0 TO SQLCODE
    END-MOCK
    MOCK SQL "ROLLBACK"
    END-MOCK
    MOCK CALL "MQBACK"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOVE "CIF0000001" TO MQ-PAY-CIF-NUMBER
    MOVE "ACCT00000001" TO MQ-PAY-ACCT-NUMBER
    MOVE 100.00 TO MQ-PAY-AMOUNT
    MOVE "DP" TO MQ-PAY-TRAN-TYPE
    MOVE "2026-07-06" TO MQ-PAY-DATE
    PERFORM 2300-DB2-INSERT
    EXPECT WS-ROWS-INSERTED TO BE 1
    EXPECT WS-DB2-ERRORS TO BE 0
    VERIFY SQL "INSERT INTO BANK. TRANSACTION_HIST" WAS PERFORMED ONCE
    VERIFY SQL "ROLLBACK" WAS PERFORMED NEVER
    VERIFY CALL "MQBACK" WAS CALLED NEVER

*> Error path: a DB2 insert failure rolls back both DB2 and the MQ get.
TESTCASE "2300-DB2-INSERT rolls back and backs out MQ on a DB2 failure"
    MOCK SQL "INSERT INTO BANK. TRANSACTION_HIST"
        MOVE -911 TO SQLCODE
    END-MOCK
    MOCK SQL "ROLLBACK"
    END-MOCK
    MOCK CALL "MQBACK"
        MOVE 0 TO MQ-COMP-CODE
    END-MOCK
    MOVE "CIF0000002" TO MQ-PAY-CIF-NUMBER
    MOVE "ACCT00000002" TO MQ-PAY-ACCT-NUMBER
    MOVE 250.00 TO MQ-PAY-AMOUNT
    MOVE "WD" TO MQ-PAY-TRAN-TYPE
    MOVE "2026-07-06" TO MQ-PAY-DATE
    PERFORM 2300-DB2-INSERT
    EXPECT WS-DB2-ERRORS TO BE 1
    VERIFY CALL "MQBACK" WAS CALLED ONCE
    VERIFY SQL "ROLLBACK" WAS PERFORMED ONCE
```

- [ ] **Step 4: Write `tests/integration/test_realworld_deptmqc_example.py`**

```python
"""End-to-end proof for the real-world DEPTMQC (MQ deposit consumer)
example -- mixes MQGET, DB2 INSERT, and a dual-commit/backout pattern
(MQCMIT+COMMIT together, ROLLBACK+MQBACK together on failure), adapted
from the sibling legacy-application repo's banking batch corpus and
compiled with GnuCOBOL in the mockymock-cobc container."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "real-world" / "DEPTMQC"
)


@requires_docker
def test_committed_deptmqc_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTMQC.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "DEPTMQC.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_deptmqc_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "DEPTMQC.cut").read_text()
    broken = tmp_path / "DEPTMQC.cut"
    broken.write_text(
        cut.replace(
            "EXPECT WS-ROWS-INSERTED TO BE 1", "EXPECT WS-ROWS-INSERTED TO BE 2"
        )
    )
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTMQC.cbl"),
            "--cut",
            str(broken),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 1
```

- [ ] **Step 5: Run the new tests and confirm they pass (not skipped)**

Run: `python -m pytest tests/integration/test_realworld_deptmqc_example.py -v`

Expected: both tests `PASSED`. Same guidance as Task 1 Step 5 if not.

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `python -m pytest tests/ -v`

Expected: all previously-passing tests plus all 4 new real-world tests pass.

- [ ] **Step 7: Commit**

```bash
git add examples/real-world/DEPTMQC tests/integration/test_realworld_deptmqc_example.py
git commit -m "test: add real-world DEPTMQC (MQ deposit consumer) e2e example"
```

---

## Task 3: READMEs for the real-world examples

**Files:**
- Create: `examples/real-world/README.md`
- Create: `examples/real-world/DEPTMQP/README.md`
- Create: `examples/real-world/DEPTMQC/README.md`

**Interfaces:**
- Consumes: `examples/real-world/DEPTMQP/DEPTMQP.cut` and
  `examples/real-world/DEPTMQC/DEPTMQC.cut` (Tasks 1-2) for the exact
  boundary/test-case names quoted below.
- Produces: nothing consumed by later tasks (Task 4 links to these paths
  but doesn't depend on their content).

- [ ] **Step 1: Write `examples/real-world/README.md`**

```markdown
# Real-world COBOL examples

Two worked examples adapted from the sibling `legacy-application` repo's
banking batch corpus (a purpose-built, workspace-internal "realistic
enterprise batch system" — not third-party code, no licensing
considerations) — chosen to prove mockymock against production-shaped
COBOL rather than the hand-crafted teaching programs in `examples/invupdt/`
and `examples/ordrproc/`.

| Example | What it proves | README |
|---|---|---|
| [DEPTMQP](DEPTMQP/README.md) | A stateful MQ CALL sequence (`MQCONN → MQOPEN → MQPUT → MQCMIT → MQCLOSE → MQDISC`) threading a connection handle across mocked calls | [DEPTMQP/README.md](DEPTMQP/README.md) |
| [DEPTMQC](DEPTMQC/README.md) | Mixed MQ + DB2 boundaries with a dual-commit/backout pattern | [DEPTMQC/README.md](DEPTMQC/README.md) |

Both programs are copied close to verbatim from their source, with one
purely cosmetic fix applied to each: `copybooks/MQMSG.cpy`'s
`MQ-QUEUE-NAME` declaration originally ran one character past COBOL
fixed-format's column-72 program-text boundary (columns 73-80 are the
identification area and are silently truncated), dropping its terminating
period and causing a real compile failure — re-wrapped onto two lines, no
logic change.

**Note on driving these programs:** neither example's `.cut` file
`PERFORM`s the program's own real entry point (`0000-MAIN-PROCESS`) —
both end in an unconditional `STOP RUN`, which would kill mockymock's test
harness mid-case (see the main [README](../../README.md)'s "Known
limitation" note). Each `.cut` instead targets sub-paragraphs directly
(`1000-INITIALIZE`, `2000-PROCESS-DEPOSITS`, `2300-DB2-INSERT`), seeding
input records via `MOVE` setup statements rather than relying on a mocked
`READ`'s tally. This proves each program's logic deterministically, one
record at a time, at the cost of not exercising the real multi-record
`READ ... UNTIL WS-EOF` loop (which lives only inside the unusable
`0000-MAIN-PROCESS`).
```

- [ ] **Step 2: Write `examples/real-world/DEPTMQP/README.md`**

```markdown
# DEPTMQP — MQ deposit producer

Adapted from `legacy-application/cobol/DEPTMQP.cbl`: reads deposit/
withdrawal records from a sequential file, validates each one, and PUTs a
message onto an IBM MQ queue, issuing `MQCMIT` periodically.

| Boundary | COBOL statement | Mock directive |
|----------|-----------------|-----------------|
| File open (2 files) | `OPEN INPUT DEPTIN`, `OPEN OUTPUT MQPRPT` | `MOCK OPEN DEPTIN`, `MOCK OPEN MQPRPT` |
| Sequential read | `READ DEPTIN AT END ...` | `MOCK READ DEPTIN` |
| Report write | `WRITE RPT-RECORD FROM ...` | `MOCK WRITE RPT-RECORD` |
| MQ connect | `CALL 'MQCONN' USING ...` | `MOCK CALL "MQCONN"` |
| MQ open | `CALL 'MQOPEN' USING ...` | `MOCK CALL "MQOPEN"` |
| MQ put | `CALL 'MQPUT' USING ...` | `MOCK CALL "MQPUT"` |
| MQ commit | `CALL 'MQCMIT' USING ...` | `MOCK CALL "MQCMIT"` |

Four test cases, two target paragraphs:

- **`1000-INITIALIZE`** (connect + open + prime first read): a happy path
  where MQCONN/MQOPEN both succeed, and an error path where MQCONN fails —
  proving `IF MQ-CONNECTED PERFORM 1200-MQ-OPEN` actually guards the open
  call (`VERIFY CALL "MQOPEN" WAS CALLED NEVER`), not just that mockymock
  requires a mock for it (`MQOPEN` is *statically* reachable from
  `1000-INITIALIZE` either way, so both test cases must mock it).
- **`2000-PROCESS-DEPOSITS`** (per-record validate/put/write): a happy
  path posting a valid record through the mocked `MQPUT`, and an error
  path where a blank CIF number fails validation before `MQPUT` is ever
  reached — again, `MQPUT`/`MQCMIT` need mocks in both cases (statically
  reachable) but the error case's `VERIFY CALL "MQPUT" WAS CALLED NEVER`
  proves the validation short-circuit actually works.

**Neither test case `PERFORM`s `0000-MAIN-PROCESS`** — see the parent
[README](../README.md) for why (`STOP RUN`).

**Mock bodies use bare literals, never named MQ-constant fields, for
non-zero values** (`MOVE 2 TO MQ-COMP-CODE`, not `MOVE MQCC-FAILED TO
MQ-COMP-CODE`) — mockymock's WORKING-STORAGE reset between test cases
zero-fills a group's named-constant children rather than restoring their
individual `VALUE` clauses (a known limitation — see
[splicer](../../../.okf/splicer.md)'s WORKING-STORAGE Reset section).
`MQCC-OK` (`VALUE +0`) survives this by coincidence; other constants don't.

Run it:

```bash
mockymock run examples/real-world/DEPTMQP/DEPTMQP.cbl \
    --cut examples/real-world/DEPTMQP/DEPTMQP.cut \
    --copybook-path examples/real-world/DEPTMQP/copybooks
```
```

- [ ] **Step 3: Write `examples/real-world/DEPTMQC/README.md`**

```markdown
# DEPTMQC — MQ deposit consumer

Adapted from `legacy-application/cobol/DEPTMQC.cbl`: drains an IBM MQ queue
with `MQGET`, validates each payload, and posts it to a DB2 table —
mixing MQ and SQL boundaries in one program, with a *dual-commit/backout*
pattern (`MQCMIT` and DB2 `COMMIT` issued together each periodic commit;
on an INSERT failure, `ROLLBACK` and `CALL 'MQBACK'` undo both sides
together so the message returns to the queue for reprocessing).

| Boundary | COBOL statement | Mock directive |
|----------|-----------------|-----------------|
| File open | `OPEN OUTPUT MQCRPT` | `MOCK OPEN MQCRPT` |
| Report write | `WRITE RPT-RECORD FROM ...` | `MOCK WRITE RPT-RECORD` |
| MQ connect | `CALL 'MQCONN' USING ...` | `MOCK CALL "MQCONN"` |
| MQ open | `CALL 'MQOPEN' USING ...` | `MOCK CALL "MQOPEN"` |
| DB2 insert | `EXEC SQL INSERT INTO BANK.TRANSACTION_HIST ... END-EXEC` | `MOCK SQL "INSERT INTO BANK. TRANSACTION_HIST"` |
| DB2 rollback | `EXEC SQL ROLLBACK END-EXEC` | `MOCK SQL "ROLLBACK"` |
| MQ backout | `CALL 'MQBACK' USING ...` | `MOCK CALL "MQBACK"` |

Four test cases, two target paragraphs — same connect/fail-connect pair as
DEPTMQP's `1000-INITIALIZE` (see [DEPTMQP's README](../DEPTMQP/README.md)
for why both a happy and MQCONN-failure case are needed), plus:

- **`2300-DB2-INSERT`**: a happy path where the INSERT succeeds
  (`SQLCODE = 0`), and an error path forcing `SQLCODE = -911` — proving
  the failure branch performs `2310-MQ-BACKOUT` (`ROLLBACK` +
  `CALL "MQBACK"`), both of which need mocks in the happy-path case too
  (statically reachable from `2300-DB2-INSERT`) but must never fire there
  (`VERIFY ... WAS CALLED NEVER` / `WAS PERFORMED NEVER`).

**Schema-qualified table name spacing**: `MOCK SQL "INSERT INTO
BANK. TRANSACTION_HIST"` has a space after the period — not a typo.
cobolparser's lexer tokenizes `BANK.TRANSACTION_HIST` as three tokens
(`BANK`, `.`, `TRANSACTION_HIST`), and mockymock's SQL-prefix match text
re-joins tokens with single spaces, so the un-spaced form never matches.

**Neither test case `PERFORM`s `0000-MAIN-PROCESS`** — see the parent
[README](../README.md) for why (`STOP RUN`).

Run it:

```bash
mockymock run examples/real-world/DEPTMQC/DEPTMQC.cbl \
    --cut examples/real-world/DEPTMQC/DEPTMQC.cut \
    --copybook-path examples/real-world/DEPTMQC/copybooks
```
```

- [ ] **Step 4: Commit**

```bash
git add examples/real-world/README.md examples/real-world/DEPTMQP/README.md examples/real-world/DEPTMQC/README.md
git commit -m "docs: READMEs for the real-world DEPTMQP/DEPTMQC examples"
```

---

## Task 4: OKF bundle and top-level README updates

**Files:**
- Modify: `.okf/testing.md`
- Modify: `.okf/log.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the boundary tables and file paths from Tasks 1-3 (this task
  only writes documentation, no code).

- [ ] **Step 1: Add a "Real-world examples" subsection to `.okf/testing.md`**

The file's `## Worked examples (examples/)` section ends with the ORDRPROC
subsection's `Run:` line, immediately followed by the `# CI` section
header. Use the Edit tool to insert the new subsection between them:

Find:
```
Run: `mockymock run ORDRPROC.cbl --cut ORDRPROC.cut`

# CI (.github/workflows/ci.yml)
```

Replace with:
```
Run: `mockymock run ORDRPROC.cbl --cut ORDRPROC.cut`

## Real-world examples (examples/real-world/)

Two further worked examples, adapted close to verbatim from the sibling
`legacy-application` repo's banking batch corpus rather than hand-written
for teaching, proving mockymock against production-shaped complexity: a
stateful multi-call MQ sequence and a mixed MQ+DB2 program with a
dual-commit/backout pattern. Each is driven by test cases that target
sub-paragraphs directly rather than the program's own entry point, because
`0000-MAIN-PROCESS` in both source programs ends in an unconditional
`STOP RUN`, which kills mockymock's test harness mid-case if `PERFORM`ed
from a `.cut` file (see the main README's "Known limitation" note) --
input records are seeded via `.cut` `MOVE` setup statements instead of a
mocked `READ`'s tally.

### DEPTMQP (examples/real-world/DEPTMQP/)

| Boundary | COBOL statement | Mock directive |
|----------|-----------------|-----------------|
| File open (2 files) | `OPEN INPUT DEPTIN`, `OPEN OUTPUT MQPRPT` | `MOCK OPEN DEPTIN`, `MOCK OPEN MQPRPT` |
| Sequential read | `READ DEPTIN AT END ...` | `MOCK READ DEPTIN` |
| Report write | `WRITE RPT-RECORD FROM ...` | `MOCK WRITE RPT-RECORD` |
| MQ connect/open/put/commit | `CALL 'MQCONN'/'MQOPEN'/'MQPUT'/'MQCMIT' USING ...` | `MOCK CALL "MQCONN"` / `"MQOPEN"` / `"MQPUT"` / `"MQCMIT"` |

Run: `mockymock run examples/real-world/DEPTMQP/DEPTMQP.cbl --cut examples/real-world/DEPTMQP/DEPTMQP.cut --copybook-path examples/real-world/DEPTMQP/copybooks`

### DEPTMQC (examples/real-world/DEPTMQC/)

| Boundary | COBOL statement | Mock directive |
|----------|-----------------|-----------------|
| File open | `OPEN OUTPUT MQCRPT` | `MOCK OPEN MQCRPT` |
| Report write | `WRITE RPT-RECORD FROM ...` | `MOCK WRITE RPT-RECORD` |
| MQ connect/open/backout | `CALL 'MQCONN'/'MQOPEN'/'MQBACK' USING ...` | `MOCK CALL "MQCONN"` / `"MQOPEN"` / `"MQBACK"` |
| DB2 insert | `EXEC SQL INSERT INTO BANK.TRANSACTION_HIST ... END-EXEC` | `MOCK SQL "INSERT INTO BANK. TRANSACTION_HIST"` (note the space after the period -- cobolparser tokenizes the schema-qualified name as three tokens and mockymock's match text re-joins them with single spaces) |
| DB2 rollback | `EXEC SQL ROLLBACK END-EXEC` | `MOCK SQL "ROLLBACK"` |

Run: `mockymock run examples/real-world/DEPTMQC/DEPTMQC.cbl --cut examples/real-world/DEPTMQC/DEPTMQC.cut --copybook-path examples/real-world/DEPTMQC/copybooks`

# CI (.github/workflows/ci.yml)
```

Also add `test_realworld_deptmqp_example.py` and
`test_realworld_deptmqc_example.py` to the file's existing sentence that
lists integration test files by name (the paragraph starting "Integration
tests need a real GnuCOBOL compiler..." near the top, or the sentence
naming `test_invupdt_example.py`/`test_ordrproc_example.py` in the Worked
Examples intro paragraph -- append these two names to whichever sentence
already enumerates the existing example test files).

The frontmatter `timestamp` at the top of the file is already
`2026-07-06T00:00:00Z` (set when this OKF bundle was initialized earlier
today) — leave it unchanged unless this task is executed on a different
date, in which case update it to that date.

- [ ] **Step 2: Append a dated entry to `.okf/log.md`**

Add an entry (following the existing entries' style — bullet, bold lead-in,
concept links) along these lines:

```markdown
* **Added real-world DEPTMQP/DEPTMQC e2e examples** ([testing](testing.md)):
  two programs adapted from the sibling `legacy-application` banking corpus
  under `examples/real-world/`, proving mockymock against production-shaped
  complexity (a stateful multi-call MQ sequence; a mixed MQ+DB2 program with
  a dual-commit/backout pattern) beyond the hand-crafted INVUPDT/ORDRPROC
  teaching examples. A third candidate (ACCTMNT, for DB2-cursor depth) was
  spiked but dropped: cobol-parser silently drops two of its EXEC SQL
  statements from the AST with no parse error, so mockymock never sees them
  to splice out and GnuCOBOL fails to compile the raw leftover text,
  regardless of which paragraph a test targets. Filed as a cobol-parser
  follow-up, along with a small, separately-verified `sqlca.py` fix
  (recognize `DECLARE ... CURSOR` in the DATA DIVISION the same way
  `DECLARE ... TABLE` already is) that would unblock a DB2-cursor example
  once the AST gap is fixed upstream. See
  `docs/2026-07-06-realworld-cobol-examples-design.md` for the full
  spike/decision trail.
```

- [ ] **Step 3: Add a pointer from the top-level `README.md`**

Use the Edit tool:

Find:
```
statements inside another boundary statement's clause body
(`READ ... AT END`, `CALL ... ON EXCEPTION`), and mocks with clause bodies
of their own — each refusal names the exact layout problem. `DISPLAY`
passes through unmocked. See the worked example in `examples/invupdt/`.
```

Replace with:
```
statements inside another boundary statement's clause body
(`READ ... AT END`, `CALL ... ON EXCEPTION`), and mocks with clause bodies
of their own — each refusal names the exact layout problem. `DISPLAY`
passes through unmocked. See the worked example in `examples/invupdt/`, or
`examples/real-world/` for two examples adapted from real banking batch
programs (a stateful MQ CALL sequence; a mixed MQ+DB2 program).
```

- [ ] **Step 4: Run the OKF validator**

Run: `/okf:validate .okf --strict` (or, if that skill/command isn't
available in the executing environment, manually confirm every concept
file touched still has non-empty YAML frontmatter with a `type` field, and
that no markdown links were broken by the edits).

Expected: no errors.

- [ ] **Step 5: Run the full test suite one final time**

Run: `python -m pytest tests/ -v`

Expected: all tests pass (this task only touched documentation, so this is
a final sanity check, not expected to find anything).

- [ ] **Step 6: Commit**

```bash
git add .okf/testing.md .okf/log.md README.md
git commit -m "docs: OKF bundle + README updates for real-world examples"
```

---

## Self-review notes (for whoever executes this plan)

- **Spec coverage:** Task 1-2 cover the design's "Structure"/"Adaptation
  policy"/"Testing" sections for both examples. Task 3 covers
  "Documentation updates"' `examples/real-world/README.md` +
  per-example READMEs. Task 4 covers the remaining `.okf/testing.md` /
  `.okf/log.md` / top-level `README.md` items. ACCTMNT, the `sqlca.py`
  fix, and the cobol-parser bug are explicitly out of scope per the
  design's "Out of scope" section and this plan's Global Constraints.
- **Every `.cut` file and integration test in Tasks 1-2 reproduces content
  already run against the real GnuCOBOL toolchain during design** (4/4
  passing for each example) — Step 5 in each task is a *confirmation* that
  the copy was faithful, not a first attempt.
- If Step 5 of Task 1 or 2 fails, the most likely cause is a
  transcription error (whitespace, a missing `END-MOCK`, wrong copybook
  path) rather than a genuine new discovery — re-diff against this plan's
  exact text before suspecting anything deeper.
