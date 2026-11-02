# mockymock: behaviour baselines (`run --record-baseline` / `--baseline`)

Date: 2026-11-01
Status: implemented (v1)

## Why

LegacyLens maps a load module and builds a mocky-mock suite for it in which
every boundary leaving the module is mocked (`USE REAL CALL`,
docs/2026-11-01-real-call-integration-design.md). A small change to a shared
copybook or subprogram can reach hundreds of load modules. The question then
is: does each of them still behave exactly as before?

`EXPECT` and `VERIFY` only check what someone thought to assert. A baseline
checks everything the module sends out: run the suite once, record its
behaviour, and compare every later run with that recording. Accepting a
change means recording a new baseline.

## What is recorded

For each test case, in order:

- **Each mocked boundary the case reaches**, as `<label> <key>`
  (`CALL DATEUTL`, `WRITE LOG-LINE`, `SQL SELECT`, `dynamic CALL WS-AUDIT-PGM`).
- **What the program sent to it**, as the hexadecimal of the bytes:
  - CALL (static, dynamic, MQ, `CBLTDLI`): each USING argument, before the
    mock body runs. An argument that is not a data item (a literal,
    `OMITTED`, `ADDRESS OF`) is recorded as `-`, so positions stay aligned.
  - WRITE / REWRITE / RELEASE: the record, after the FROM copy.
  - EXEC SQL: each host variable outside an INTO list, in order, once.
    An `OPEN` of a cursor is followed by a `SQL CURSOR <name>` event with
    the host variables of the cursor's `DECLARE` (what DB2 reads at OPEN;
    the DECLARE itself is not a statement that runs). Since version 2.
  - EXEC CICS: the FROM and COMMAREA items.
  - Other boundaries (OPEN, READ, ACCEPT, ...): the event alone.
- **What the program hands back to its caller**, at the end of each case,
  as a `RETURNED LINKAGE` event: the bytes of each item of its
  `PROCEDURE DIVISION USING` and, for a CICS program, its `DFHCOMMAREA`.
  A called subprogram or a CICS `LINK` target does all its work through
  these, so without them a change to its result compared as the same.
  Since version 2.
- **The program's own DISPLAY output** while the case ran.
- **The RETURN-CODE** the case ended with, and its status (passed, failed,
  crashed).

A `USE REAL CALL` is not recorded. It stays inside the load module, and a
refactor may change it without changing what the module does.

Values are hexadecimal so a COMP-3 or binary field is compared byte for
byte: stdout is decoded as UTF-8 with replacement, which would merge two
different non-text bytes into one character. The bytes are printed by
`UTHEXDMP`, a small program compiled into the same binary
(`splicer.behaviour.hexdump_program`). It takes the item by reference with
its `LENGTH OF`, so it works on any item and on GnuCOBOL 3.1 as well as 3.2
(`FUNCTION HEX-OF` is 3.2 only). A value longer than 32,768 bytes is cut
there and ends in `+`.

## The file

```json
{
  "format": "mockymock-baseline",
  "version": 2,
  "suite": "ORDMAIN load module: validate, publish, log",
  "recorded_at": "2026-11-01T22:10:00+00:00",
  "mockymock": "0.12.0",
  "inputs": {"cut": "<sha256>", "program": "<sha256>", "real:ORDVAL": "<sha256>"},
  "cases": [
    {
      "name": "orders under the limit are published, one over it is rejected",
      "status": "passed",
      "return_code": "+000000000",
      "events": [
        {"label": "CALL DATEUTL", "data": ["2020202020202020"]},
        {"label": "WRITE LOG-LINE", "data": ["4F3030303031204F4B20..."]}
      ],
      "output": []
    }
  ]
}
```

Version 2 (2026-11-02) added the cursor and returned-LINKAGE events.
A version-1 baseline is still read: the comparison leaves those events out
of the new run and adds a note (`notes` in `--baseline-json`) saying they
were not compared until a new baseline is recorded.

`inputs` holds the SHA-256 of the `.cut`, the entry program and each real
program. A comparison lists the ones that changed. A changed `.cut` is called
out: its mocks may answer differently, so a difference may come from the
mocks and not from the code.

## Comparing

`--baseline FILE` runs the suite with the same instrumentation and matches
cases by name:

- `SAME`: identical events, values, output, RETURN-CODE and status.
- `DIFFERS`: the first differing event (and which value), the first
  differing output line, the RETURN-CODE or status change. When both values
  are printable text, the text is shown next to the hex.
- `NEW`: a case with no baseline. Reported, does not fail.
- `NOT RUN`: in the baseline, not in this run (`--case`/`--tag`). Reported,
  does not fail.

The run exits 1 when any case differs, even if every `EXPECT` passed.
`--baseline-json` writes the comparison for a caller such as the LegacyLens
runner. `--record-baseline` and `--baseline` can be given together to
compare and then replace the baseline.

## Not covered (v1)

- `debug`, `export` and `mutate` do not take the flags.
- What a mock *answers* is not recorded: it comes from the `.cut`, which is
  the input that has to stay the same.
- A value sent to a boundary that the mock body later overwrites (an
  output-only CALL argument) is recorded with the value it had before the
  call. That is deterministic, so it compares correctly, but it can make a
  change to an unused initial value show up as a difference.
- Line numbers are not part of an event, so moving code without changing
  what it does compares as the same.
