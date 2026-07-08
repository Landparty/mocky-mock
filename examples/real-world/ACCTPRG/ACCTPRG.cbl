       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPRG.
      *****************************************************************
      * PROGRAM:   ACCTPRG                                            *
      * PURPOSE:   ACCOUNT PURGE IMS DL/I BATCH PROCESSOR             *
      *            SCANS ALL CUSTSEG SEGMENTS IN CUSTDB AND DELETES   *
      *            CLOSED ACCOUNTS INACTIVE BEYOND THE PURGE CUTOFF.  *
      * INPUT:     PURGEIN - PURGE CONTROL CARD (CUTOFF DATE YYYYMMDD)*
      * OUTPUT:    PURGRPT - ACCOUNT PURGE AUDIT REPORT               *
      * ENTRY:     DLITCBL (IMS DL/I BATCH - NO MESSAGE QUEUE)        *
      * PCBs:      CUST-PCB-LNK (CUSTDB, PROCOPT=A ON CUSTSEG)       *
      * PSB:       ACCTPPSB                                           *
      * PROC:      DLIBATCH (IBM DL/I BATCH REGION CONTROLLER)        *
      * FREQ:      QUARTERLY - SUBMITTED VIA ACCTPRGJ.JCL            *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PURGEIN  ASSIGN TO PURGEIN
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-PURGEIN-STATUS.
           SELECT PURGRPT  ASSIGN TO PURGRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  PURGEIN
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  PURGEIN-REC.
           05  PURG-CUTOFF-DATE     PIC X(08).
           05  PURG-ACCT-STATUS     PIC X(02).
           05  FILLER               PIC X(70).

       FD  PURGRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD               PIC X(133).

       WORKING-STORAGE SECTION.
           COPY WSCOMMON.
           COPY ERRORCD.
           COPY IMSPCB.

       01  WS-PURGEIN-STATUS        PIC X(02).
           88  WS-PURGEIN-OK        VALUE '00'.

       01  WS-PURGE-PARMS.
           05  WS-CUTOFF-DATE       PIC X(08) VALUE '        '.
           05  WS-TARGET-STATUS     PIC X(02) VALUE 'CL'.

       01  WS-CUSTSEG-IO.
           05  CUST-IO-CIF          PIC X(10).
           05  CUST-IO-ACCT         PIC X(12).
           05  CUST-IO-STATUS       PIC X(02).
           05  CUST-IO-LAST-ACT     PIC X(08).
           05  CUST-IO-OPEN-DATE    PIC X(08).
           05  CUST-IO-CLOSE-DATE   PIC X(08).
           05  CUST-IO-ACCT-TYPE    PIC X(04).
           05  FILLER               PIC X(448).

       01  WS-PURGE-COUNTERS.
           05  WS-SEGS-SCANNED      PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-SEGS-PURGED       PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-SEGS-SKIPPED      PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-PURGE-ERRORS      PIC 9(05) COMP-3 VALUE ZERO.

       01  WS-RECORD-ERROR          PIC X(01) VALUE 'N'.
           88  RECORD-ERROR-FOUND   VALUE 'Y'.
           88  RECORD-OK            VALUE 'N'.

       01  WS-HDR.
           05  FILLER PIC X(10) VALUE 'CIF       '.
           05  FILLER PIC X(14) VALUE 'ACCOUNT       '.
           05  FILLER PIC X(06) VALUE 'STATUS'.
           05  FILLER PIC X(10) VALUE ' LAST-ACT '.
           05  FILLER PIC X(10) VALUE ' CLOSE-DT '.
           05  FILLER PIC X(12) VALUE ' ACTION     '.

       01  WS-DETAIL.
           05  WS-DET-CIF           PIC X(10).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-ACCT          PIC X(12).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-STATUS        PIC X(02).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-LAST-ACT      PIC X(08).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-CLOSE         PIC X(08).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-ACTION        PIC X(14).
           05  FILLER               PIC X(77) VALUE SPACES.

       LINKAGE SECTION.
       01  CUST-PCB-LNK.
           05  CUST-DBD-NAME        PIC X(08).
           05  CUST-SEG-LEVEL       PIC X(02).
           05  CUST-STATUS          PIC X(02).
               88  CUST-PCB-OK      VALUE '  '.
               88  CUST-PCB-NF      VALUE 'GE'.
               88  CUST-PCB-EOD     VALUE 'GB'.
           05  CUST-PROC-OPTIONS    PIC X(04).
           05  CUST-RESERVED        PIC S9(05) COMP.
           05  CUST-SEG-NAME        PIC X(08).
           05  CUST-KEY-LEN         PIC S9(05) COMP.
           05  CUST-NUM-SENS-SEGS   PIC S9(05) COMP.
           05  CUST-KEY-FEEDBACK    PIC X(30).

       PROCEDURE DIVISION.
       ENTRY 'DLITCBL' USING CUST-PCB-LNK.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-SCAN-AND-PURGE
               UNTIL WS-EOF
           PERFORM 3000-FINALIZE
           GOBACK.

       1000-INITIALIZE.
           DISPLAY 'ACCTPRG: ACCOUNT PURGE DL/I BATCH STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR  DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-MONTH DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-DAY   DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING
           OPEN INPUT  PURGEIN
           OPEN OUTPUT PURGRPT
           WRITE RPT-RECORD FROM WS-HDR
           READ PURGEIN
               NOT AT END
                   MOVE PURG-CUTOFF-DATE  TO WS-CUTOFF-DATE
                   MOVE PURG-ACCT-STATUS  TO WS-TARGET-STATUS
           END-READ
           DISPLAY 'ACCTPRG: PURGE CUTOFF DATE=' WS-CUTOFF-DATE
           DISPLAY 'ACCTPRG: TARGET STATUS     =' WS-TARGET-STATUS
      *    PRIME THE GHN LOOP WITH THE FIRST CUSTSEG SEGMENT
           CALL 'CBLTDLI' USING DLI-GHN
                                CUST-PCB-LNK
                                WS-CUSTSEG-IO
                                SSA-UNQUAL-CUST
           EVALUATE CUST-STATUS
               WHEN '  '
                   CONTINUE
               WHEN 'GB'
                   DISPLAY 'ACCTPRG: CUSTDB IS EMPTY - NOTHING TO PURGE'
                   SET WS-EOF TO TRUE
               WHEN OTHER
                   DISPLAY 'ACCTPRG: INIT GHN ERROR STATUS=' CUST-STATUS
                   SET WS-EOF TO TRUE
           END-EVALUATE.

       2000-SCAN-AND-PURGE.
           ADD 1 TO WS-SEGS-SCANNED
           MOVE 'N' TO WS-RECORD-ERROR
           PERFORM 2100-EVALUATE-PURGE-CRITERIA
           IF RECORD-OK
               PERFORM 2200-DLET-CUSTSEG
           ELSE
               ADD 1 TO WS-SEGS-SKIPPED
               MOVE 'SKIPPED       ' TO WS-DET-ACTION
           END-IF
           PERFORM 2400-WRITE-DETAIL
           PERFORM 2500-GET-NEXT-SEGMENT.

       2100-EVALUATE-PURGE-CRITERIA.
      *    ELIGIBLE: STATUS MATCHES TARGET AND LAST ACTIVITY BEFORE CUTOFF
           IF CUST-IO-STATUS NOT = WS-TARGET-STATUS
               MOVE 'N' TO WS-RECORD-ERROR
               SET RECORD-ERROR-FOUND TO TRUE
               EXIT PARAGRAPH
           END-IF
           IF CUST-IO-LAST-ACT > WS-CUTOFF-DATE
               MOVE 'N' TO WS-RECORD-ERROR
               SET RECORD-ERROR-FOUND TO TRUE
           END-IF.

       2200-DLET-CUSTSEG.
      *    GHN ALREADY HOLDS THE SEGMENT; DLET REMOVES IT AND ALL CHILDREN
           CALL 'CBLTDLI' USING DLI-DLET
                                CUST-PCB-LNK
                                WS-CUSTSEG-IO
           EVALUATE CUST-STATUS
               WHEN '  '
                   ADD 1 TO WS-SEGS-PURGED
                   MOVE 'PURGED        ' TO WS-DET-ACTION
               WHEN OTHER
                   ADD 1 TO WS-PURGE-ERRORS
                   MOVE 'DLET ERROR    ' TO WS-DET-ACTION
                   DISPLAY 'ACCTPRG: DLET ERROR STATUS=' CUST-STATUS
                           ' CIF=' CUST-IO-CIF
           END-EVALUATE.

       2400-WRITE-DETAIL.
           MOVE CUST-IO-CIF       TO WS-DET-CIF
           MOVE CUST-IO-ACCT      TO WS-DET-ACCT
           MOVE CUST-IO-STATUS    TO WS-DET-STATUS
           MOVE CUST-IO-LAST-ACT  TO WS-DET-LAST-ACT
           MOVE CUST-IO-CLOSE-DATE TO WS-DET-CLOSE
           WRITE RPT-RECORD FROM WS-DETAIL.

       2500-GET-NEXT-SEGMENT.
      *    GHN HOLDS THE NEXT SEGMENT FOR POTENTIAL DLET IN NEXT ITERATION
           CALL 'CBLTDLI' USING DLI-GHN
                                CUST-PCB-LNK
                                WS-CUSTSEG-IO
                                SSA-UNQUAL-CUST
           EVALUATE CUST-STATUS
               WHEN '  '
                   CONTINUE
               WHEN 'GB'
                   SET WS-EOF TO TRUE
               WHEN OTHER
                   ADD 1 TO WS-PURGE-ERRORS
                   DISPLAY 'ACCTPRG: GHN ERROR STATUS=' CUST-STATUS
                   SET WS-EOF TO TRUE
           END-EVALUATE.

       3000-FINALIZE.
           CLOSE PURGEIN
           CLOSE PURGRPT
           DISPLAY 'ACCTPRG: ACCOUNT PURGE DL/I BATCH COMPLETE'
           DISPLAY 'SEGMENTS SCANNED: ' WS-SEGS-SCANNED
           DISPLAY 'SEGMENTS PURGED:  ' WS-SEGS-PURGED
           DISPLAY 'SEGMENTS SKIPPED: ' WS-SEGS-SKIPPED
           DISPLAY 'PURGE ERRORS:     ' WS-PURGE-ERRORS
           IF WS-PURGE-ERRORS > ZERO
               MOVE 8 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
