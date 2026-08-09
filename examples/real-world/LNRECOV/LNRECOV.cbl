       IDENTIFICATION DIVISION.
       PROGRAM-ID. LNRECOV.
      *****************************************************************
      * PROGRAM:   LNRECOV                                            *
      * PURPOSE:   LOAN RECOVERY IMS DBB BATCH PROCESSOR              *
      *            SCANS LOANDB FOR DELINQUENT LOANS EXCEEDING THE    *
      *            DAYS-PAST-DUE THRESHOLD AND MARKS THEM FOR         *
      *            RECOVERY VIA REPL ON THE LOANSEG SEGMENT.          *
      * INPUT:     RECOVIN - RECOVERY CONTROL CARD (DPD-THRESHOLD)   *
      * OUTPUT:    RECOVRPT - LOAN RECOVERY AUDIT REPORT              *
      * ENTRY:     DLITCBL (IMS DBB BATCH - DYNAMIC BACKOUT VIA DBRC)*
      * PCBs:      LOAN-PCB-LNK (LOANDB, PROCOPT=A ON LOANSEG)      *
      * PSB:       LNRECPSB                                           *
      * PROC:      DBBBATCH (IBM DBB BATCH REGION CONTROLLER)         *
      * FREQ:      MONTHLY - SUBMITTED VIA LNRECOVJ.JCL              *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RECOVIN  ASSIGN TO RECOVIN
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-RECOVIN-STATUS.
           SELECT RECOVRPT  ASSIGN TO RECOVRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  RECOVIN
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RECOVIN-REC.
           05  RECOV-DPD-THRESHOLD  PIC 9(03).
           05  RECOV-MIN-BALANCE    PIC X(15).
           05  FILLER               PIC X(62).

       FD  RECOVRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD               PIC X(133).

       WORKING-STORAGE SECTION.
           COPY WSCOMMON.
           COPY ERRORCD.
           COPY IMSPCB.

       01  WS-RECOVIN-STATUS        PIC X(02).
           88  WS-RECOVIN-OK        VALUE '00'.

       01  WS-RECOV-PARMS.
           05  WS-DPD-THRESHOLD     PIC 9(03) VALUE 090.
           05  WS-MIN-BAL           PIC S9(11)V99 COMP-3 VALUE ZERO.

       01  WS-LOANSEG-IO.
           05  LOAN-IO-LOAN-NUM     PIC X(12).
           05  LOAN-IO-CIF          PIC X(10).
           05  LOAN-IO-ACCT         PIC X(12).
           05  LOAN-IO-STATUS       PIC X(02).
           05  LOAN-IO-DPD          PIC 9(03).
           05  LOAN-IO-BAL-CHAR     PIC X(15).
           05  LOAN-IO-MATURITY     PIC X(08).
           05  LOAN-IO-LOAN-TYPE    PIC X(04).
           05  FILLER               PIC X(442).

       01  WS-BAL-WORK              PIC S9(11)V99 COMP-3.
       01  WS-BAL-DISP              PIC Z,ZZZ,ZZZ,ZZ9.99.

       01  WS-RECOV-COUNTERS.
           05  WS-SEGS-SCANNED      PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-SEGS-MARKED       PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-SEGS-SKIPPED      PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-REPL-ERRORS       PIC 9(05) COMP-3 VALUE ZERO.

       01  WS-RECORD-ERROR          PIC X(01) VALUE 'N'.
           88  RECORD-ERROR-FOUND   VALUE 'Y'.
           88  RECORD-OK            VALUE 'N'.

       01  WS-HDR.
           05  FILLER PIC X(12) VALUE 'LOAN-NUMBER '.
           05  FILLER PIC X(10) VALUE 'CIF       '.
           05  FILLER PIC X(04) VALUE 'DPD '.
           05  FILLER PIC X(18) VALUE '           BALANCE'.
           05  FILLER PIC X(06) VALUE 'STATUS'.
           05  FILLER PIC X(08) VALUE ' ACTION '.

       01  WS-DETAIL.
           05  WS-DET-LOAN          PIC X(12).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-CIF           PIC X(10).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-DPD           PIC ZZ9.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-BAL           PIC Z,ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-STATUS        PIC X(02).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-ACTION        PIC X(14).
           05  FILLER               PIC X(72) VALUE SPACES.

       LINKAGE SECTION.
       01  LOAN-PCB-LNK.
           05  LOAN-DBD-NAME        PIC X(08).
           05  LOAN-SEG-LEVEL       PIC X(02).
           05  LOAN-STATUS          PIC X(02).
               88  LOAN-PCB-OK      VALUE '  '.
               88  LOAN-PCB-NF      VALUE 'GE'.
               88  LOAN-PCB-EOD     VALUE 'GB'.
           05  LOAN-PROC-OPTIONS    PIC X(04).
           05  LOAN-RESERVED        PIC S9(05) COMP.
           05  LOAN-SEG-NAME        PIC X(08).
           05  LOAN-KEY-LEN         PIC S9(05) COMP.
           05  LOAN-NUM-SENS-SEGS   PIC S9(05) COMP.
           05  LOAN-KEY-FEEDBACK    PIC X(30).

       PROCEDURE DIVISION.
       ENTRY 'DLITCBL' USING LOAN-PCB-LNK.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-SCAN-AND-MARK
               UNTIL WS-EOF
           PERFORM 3000-FINALIZE
           GOBACK.

       1000-INITIALIZE.
           DISPLAY 'LNRECOV: LOAN RECOVERY DBB BATCH STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR  DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-MONTH DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-DAY   DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING
           OPEN INPUT  RECOVIN
           OPEN OUTPUT RECOVRPT
           WRITE RPT-RECORD FROM WS-HDR
           READ RECOVIN
               NOT AT END
                   MOVE RECOV-DPD-THRESHOLD TO WS-DPD-THRESHOLD
                   IF FUNCTION TEST-NUMVAL(RECOV-MIN-BALANCE) = ZERO
                       COMPUTE WS-MIN-BAL =
                           FUNCTION NUMVAL(RECOV-MIN-BALANCE)
                   END-IF
           END-READ
           DISPLAY 'LNRECOV: DPD THRESHOLD =' WS-DPD-THRESHOLD
           DISPLAY 'LNRECOV: MIN BALANCE   =' WS-MIN-BAL
      *    PRIME THE LOOP WITH THE FIRST LOANSEG - GHN HOLDS FOR REPL
           CALL 'CBLTDLI' USING DLI-GHN
                                LOAN-PCB-LNK
                                WS-LOANSEG-IO
                                SSA-UNQUAL-LOAN
           EVALUATE LOAN-STATUS
               WHEN '  '
                   CONTINUE
               WHEN 'GB'
                   DISPLAY 'LNRECOV: LOANDB IS EMPTY'
                   SET WS-EOF TO TRUE
               WHEN OTHER
                   DISPLAY 'LNRECOV: INIT GHN ERROR STATUS=' LOAN-STATUS
                   SET WS-EOF TO TRUE
           END-EVALUATE.

       2000-SCAN-AND-MARK.
           ADD 1 TO WS-SEGS-SCANNED
           MOVE 'N' TO WS-RECORD-ERROR
           PERFORM 2100-EVALUATE-RECOVERY-CRITERIA
           IF RECORD-OK
               PERFORM 2200-MARK-FOR-RECOVERY
           ELSE
               ADD 1 TO WS-SEGS-SKIPPED
               MOVE 'SKIPPED       ' TO WS-DET-ACTION
           END-IF
           PERFORM 2400-WRITE-DETAIL
           PERFORM 2500-GET-NEXT-LOAN.

       2100-EVALUATE-RECOVERY-CRITERIA.
      *    ELIGIBLE: STATUS DL (DELINQUENT), DPD OVER THRESHOLD, BAL > MIN
           IF LOAN-IO-STATUS NOT = 'DL'
               SET RECORD-ERROR-FOUND TO TRUE
               EXIT PARAGRAPH
           END-IF
           IF LOAN-IO-DPD < WS-DPD-THRESHOLD
               SET RECORD-ERROR-FOUND TO TRUE
               EXIT PARAGRAPH
           END-IF
           IF FUNCTION TEST-NUMVAL(LOAN-IO-BAL-CHAR) NOT = ZERO
               SET RECORD-ERROR-FOUND TO TRUE
               EXIT PARAGRAPH
           END-IF
           COMPUTE WS-BAL-WORK =
               FUNCTION NUMVAL(LOAN-IO-BAL-CHAR)
           IF WS-BAL-WORK < WS-MIN-BAL
               SET RECORD-ERROR-FOUND TO TRUE
           END-IF.

       2200-MARK-FOR-RECOVERY.
      *    GHN ALREADY HOLDS THE LOANSEG; UPDATE STATUS TO RC (RECOVERY)
      *    DBBBATCH ENSURES DBRC DYNAMIC BACKOUT IF JOB ABENDS MID-BATCH
           MOVE 'RC' TO LOAN-IO-STATUS
           CALL 'CBLTDLI' USING DLI-REPL
                                LOAN-PCB-LNK
                                WS-LOANSEG-IO
           EVALUATE LOAN-STATUS
               WHEN '  '
                   ADD 1 TO WS-SEGS-MARKED
                   MOVE 'MARKED RECOV  ' TO WS-DET-ACTION
               WHEN OTHER
                   ADD 1 TO WS-REPL-ERRORS
                   MOVE 'REPL ERROR    ' TO WS-DET-ACTION
                   DISPLAY 'LNRECOV: REPL ERROR STATUS=' LOAN-STATUS
                           ' LOAN=' LOAN-IO-LOAN-NUM
                   MOVE 'DL' TO LOAN-IO-STATUS
           END-EVALUATE.

       2400-WRITE-DETAIL.
           MOVE LOAN-IO-LOAN-NUM  TO WS-DET-LOAN
           MOVE LOAN-IO-CIF       TO WS-DET-CIF
           MOVE LOAN-IO-DPD       TO WS-DET-DPD
           MOVE WS-BAL-WORK       TO WS-DET-BAL
           MOVE LOAN-IO-STATUS    TO WS-DET-STATUS
           WRITE RPT-RECORD FROM WS-DETAIL.

       2500-GET-NEXT-LOAN.
      *    GHN HOLDS THE NEXT LOANSEG IN CASE THIS ITERATION NEEDS REPL
           CALL 'CBLTDLI' USING DLI-GHN
                                LOAN-PCB-LNK
                                WS-LOANSEG-IO
                                SSA-UNQUAL-LOAN
           EVALUATE LOAN-STATUS
               WHEN '  '
                   CONTINUE
               WHEN 'GB'
                   SET WS-EOF TO TRUE
               WHEN OTHER
                   ADD 1 TO WS-REPL-ERRORS
                   DISPLAY 'LNRECOV: GHN ERROR STATUS=' LOAN-STATUS
                   SET WS-EOF TO TRUE
           END-EVALUATE.

       3000-FINALIZE.
           CLOSE RECOVIN
           CLOSE RECOVRPT
           DISPLAY 'LNRECOV: LOAN RECOVERY DBB BATCH COMPLETE'
           DISPLAY 'LOANS SCANNED:      ' WS-SEGS-SCANNED
           DISPLAY 'LOANS MARKED RECOV: ' WS-SEGS-MARKED
           DISPLAY 'LOANS SKIPPED:      ' WS-SEGS-SKIPPED
           DISPLAY 'REPLACE ERRORS:     ' WS-REPL-ERRORS
           IF WS-REPL-ERRORS > ZERO
               MOVE 8 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
