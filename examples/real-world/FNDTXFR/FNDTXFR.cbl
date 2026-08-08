       IDENTIFICATION DIVISION.
       PROGRAM-ID. FNDTXFR.
      *****************************************************************
      * PROGRAM:   FNDTXFR                                            *
      * PURPOSE:   FUND TRANSFER IMS BMP BATCH PROCESSOR              *
      *            READS XFERIN TRANSFER FILE AND POSTS DEBIT/CREDIT  *
      *            TRNSEG PAIRS INTO CUSTDB FOR EACH TRANSFER.        *
      * INPUT:     XFERIN  - SEQUENTIAL TRANSFER REQUEST FILE (92 B)  *
      * OUTPUT:    XFRRPT  - FUND TRANSFER PROCESSING REPORT          *
      * ENTRY:     DLITCBL (IMS BMP)                                  *
      * PCBs:      CUST-PCB-LNK (CUSTDB, PROCOPT=A ON CUSTSEG/TRNSEG)*
      * PSB:       FNDTPSB                                            *
      * PROC:      IMSBATCH (IBM STANDARD BMP REGION CONTROLLER)      *
      * FREQ:      ON-DEMAND - SUBMITTED VIA FNDXFRJ.JCL             *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT XFERIN  ASSIGN TO XFERIN
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-XFERIN-STATUS.
           SELECT XFRRPT  ASSIGN TO XFRRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  XFERIN
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  XFERIN-REC.
           05  XFR-SRC-CIF          PIC X(10).
           05  XFR-SRC-ACCT         PIC X(12).
           05  XFR-TGT-CIF          PIC X(10).
           05  XFR-TGT-ACCT         PIC X(12).
           05  XFR-AMOUNT-CHAR      PIC X(15).
           05  XFR-DATE             PIC X(10).
           05  XFR-REF-NUM          PIC X(16).
           05  FILLER               PIC X(07).

       FD  XFRRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD               PIC X(133).

       WORKING-STORAGE SECTION.
           COPY WSCOMMON.
           COPY ERRORCD.
           COPY IMSPCB.
           COPY TRNSEG.

       01  WS-XFERIN-STATUS         PIC X(02).
           88  WS-XFERIN-OK         VALUE '00'.
           88  WS-XFERIN-EOF        VALUE '10'.

       01  WS-EDIT-WORK.
           05  WS-AMOUNT-WORK       PIC S9(11)V99 COMP-3.
           05  WS-AMOUNT-DISP       PIC Z,ZZZ,ZZZ,ZZ9.99.

       01  WS-CHKP-FREQ             PIC 9(05) COMP-3 VALUE 500.
       01  WS-CHKP-COUNT            PIC 9(05) COMP-3 VALUE ZERO.
       01  WS-CHKP-ID.
           05  FILLER               PIC X(04) VALUE 'FXFR'.
           05  WS-CHKP-SEQ          PIC 9(04).

       01  WS-XFR-COUNTERS.
           05  WS-XFR-PROCESSED     PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-XFR-ERRORS        PIC 9(05) COMP-3 VALUE ZERO.

       01  WS-RECORD-ERROR          PIC X(01) VALUE 'N'.
           88  RECORD-ERROR-FOUND   VALUE 'Y'.
           88  RECORD-OK            VALUE 'N'.

       01  WS-HDR.
           05  FILLER PIC X(10) VALUE 'SOURCE-CIF'.
           05  FILLER PIC X(02) VALUE '  '.
           05  FILLER PIC X(12) VALUE 'SOURCE-ACCT '.
           05  FILLER PIC X(10) VALUE 'TARGET-CIF'.
           05  FILLER PIC X(02) VALUE '  '.
           05  FILLER PIC X(12) VALUE 'TARGET-ACCT '.
           05  FILLER PIC X(18) VALUE '            AMOUNT'.
           05  FILLER PIC X(10) VALUE '  STATUS  '.

       01  WS-DETAIL.
           05  WS-DET-SRCCIF        PIC X(10).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-SRCACCT       PIC X(12).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-TGTCIF        PIC X(10).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-TGTACCT       PIC X(12).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-AMOUNT        PIC Z,ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-STATUS        PIC X(14).

       LINKAGE SECTION.
       01  CUST-PCB-LNK.
           05  CUST-DBD-NAME        PIC X(08).
           05  CUST-SEG-LEVEL       PIC X(02).
           05  CUST-STATUS          PIC X(02).
               88  CUST-PCB-OK      VALUE '  '.
               88  CUST-PCB-NF      VALUE 'GE'.
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
           PERFORM 2000-PROCESS-TRANSFERS
               UNTIL WS-EOF
           PERFORM 3000-FINALIZE
           GOBACK.

       1000-INITIALIZE.
           DISPLAY 'FNDTXFR: FUND TRANSFER BMP PROCESSING STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR  DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-MONTH DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-DAY   DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING
           MOVE ZERO TO WS-CHKP-SEQ
           OPEN INPUT  XFERIN
           OPEN OUTPUT XFRRPT
           WRITE RPT-RECORD FROM WS-HDR
           ADD 1 TO WS-CHKP-SEQ
           CALL 'CBLTDLI' USING DLI-CHKP
                                CUST-PCB-LNK
                                WS-CHKP-ID
           READ XFERIN
               AT END SET WS-EOF TO TRUE
           END-READ.

       2000-PROCESS-TRANSFERS.
           MOVE 'N' TO WS-RECORD-ERROR
           ADD 1 TO WS-RECS-READ
           PERFORM 2100-VALIDATE-RECORD
           IF RECORD-OK
               PERFORM 2200-POST-SOURCE-DEBIT
           END-IF
           IF RECORD-OK
               PERFORM 2300-POST-TARGET-CREDIT
           END-IF
           IF RECORD-OK
               ADD 1 TO WS-XFR-PROCESSED
               MOVE 'TRANSFER OK   ' TO WS-DET-STATUS
           ELSE
               ADD 1 TO WS-XFR-ERRORS
           END-IF
           PERFORM 2400-WRITE-DETAIL
           PERFORM 2500-CHECKPOINT
           READ XFERIN
               AT END SET WS-EOF TO TRUE
           END-READ.

       2100-VALIDATE-RECORD.
           IF XFR-SRC-CIF = SPACES OR LOW-VALUES
               MOVE 'SRC CIF MISSING' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           IF XFR-TGT-CIF = SPACES OR LOW-VALUES
               MOVE 'TGT CIF MISSING' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           IF FUNCTION TEST-NUMVAL(XFR-AMOUNT-CHAR) NOT = ZERO
               MOVE 'BAD AMOUNT    ' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           COMPUTE WS-AMOUNT-WORK =
               FUNCTION NUMVAL(XFR-AMOUNT-CHAR)
           IF WS-AMOUNT-WORK <= ZERO
               MOVE 'AMOUNT LE ZERO' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
           END-IF.

       2200-POST-SOURCE-DEBIT.
      *    GU POSITIONS IMS AT SOURCE CUSTSEG; ISRT WRITES DEBIT TRNSEG
           MOVE XFR-SRC-CIF TO SSA-CUST-KEY-VALUE
           CALL 'CBLTDLI' USING DLI-GU
                                CUST-PCB-LNK
                                IMS-IO-AREA
                                SSA-CUSTOMER
           EVALUATE CUST-STATUS
               WHEN '  '
                   CONTINUE
               WHEN 'GE'
                   MOVE 'SRC CUST NF   ' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-CUST-NOT-FOUND
                   EXIT PARAGRAPH
               WHEN OTHER
                   MOVE 'SRC DB ERROR  ' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-DB-ERRORS
                   DISPLAY 'FNDTXFR: GU SRC ERROR STATUS=' CUST-STATUS
                           ' CIF=' XFR-SRC-CIF
                   EXIT PARAGRAPH
           END-EVALUATE
           MOVE SPACES            TO TRNSEG-IO
           MOVE XFR-SRC-CIF       TO TRAN-CIF-NUMBER
           MOVE XFR-SRC-ACCT      TO TRAN-ACCT-NUMBER
           MOVE WS-AMOUNT-WORK    TO TRAN-AMOUNT
           MOVE 'WD'              TO TRAN-TYPE
           MOVE WS-BUSINESS-DATE  TO TRAN-DATE
           MOVE 'BATC'            TO TRAN-CHANNEL
           MOVE 'P'               TO TRAN-STATUS
           MOVE FUNCTION CURRENT-DATE TO TRAN-TIMESTAMP
           CALL 'CBLTDLI' USING DLI-ISRT
                                CUST-PCB-LNK
                                TRNSEG-IO
                                SSA-CUSTOMER
                                SSA-UNQUAL-TRAN
           EVALUATE CUST-STATUS
               WHEN '  '
                   ADD 1 TO WS-TRNS-INSERTED
               WHEN OTHER
                   MOVE 'DEBIT ISRT ERR' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-DB-ERRORS
                   DISPLAY 'FNDTXFR: DEBIT ISRT ERROR STATUS='
                           CUST-STATUS ' CIF=' XFR-SRC-CIF
           END-EVALUATE.

       2300-POST-TARGET-CREDIT.
      *    GU POSITIONS IMS AT TARGET CUSTSEG; ISRT WRITES CREDIT TRNSEG
           MOVE XFR-TGT-CIF TO SSA-CUST-KEY-VALUE
           CALL 'CBLTDLI' USING DLI-GU
                                CUST-PCB-LNK
                                IMS-IO-AREA
                                SSA-CUSTOMER
           EVALUATE CUST-STATUS
               WHEN '  '
                   CONTINUE
               WHEN 'GE'
                   MOVE 'TGT CUST NF   ' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-CUST-NOT-FOUND
                   EXIT PARAGRAPH
               WHEN OTHER
                   MOVE 'TGT DB ERROR  ' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-DB-ERRORS
                   DISPLAY 'FNDTXFR: GU TGT ERROR STATUS=' CUST-STATUS
                           ' CIF=' XFR-TGT-CIF
                   EXIT PARAGRAPH
           END-EVALUATE
           MOVE SPACES            TO TRNSEG-IO
           MOVE XFR-TGT-CIF       TO TRAN-CIF-NUMBER
           MOVE XFR-TGT-ACCT      TO TRAN-ACCT-NUMBER
           MOVE WS-AMOUNT-WORK    TO TRAN-AMOUNT
           MOVE 'DP'              TO TRAN-TYPE
           MOVE WS-BUSINESS-DATE  TO TRAN-DATE
           MOVE 'BATC'            TO TRAN-CHANNEL
           MOVE 'P'               TO TRAN-STATUS
           MOVE FUNCTION CURRENT-DATE TO TRAN-TIMESTAMP
           CALL 'CBLTDLI' USING DLI-ISRT
                                CUST-PCB-LNK
                                TRNSEG-IO
                                SSA-CUSTOMER
                                SSA-UNQUAL-TRAN
           EVALUATE CUST-STATUS
               WHEN '  '
                   ADD 1 TO WS-TRNS-INSERTED
               WHEN OTHER
                   MOVE 'CREDIT ISRT ER' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-DB-ERRORS
                   DISPLAY 'FNDTXFR: CREDIT ISRT ERROR STATUS='
                           CUST-STATUS ' CIF=' XFR-TGT-CIF
           END-EVALUATE.

       2400-WRITE-DETAIL.
           MOVE XFR-SRC-CIF      TO WS-DET-SRCCIF
           MOVE XFR-SRC-ACCT     TO WS-DET-SRCACCT
           MOVE XFR-TGT-CIF      TO WS-DET-TGTCIF
           MOVE XFR-TGT-ACCT     TO WS-DET-TGTACCT
           IF WS-AMOUNT-WORK > ZERO
               MOVE WS-AMOUNT-WORK TO WS-DET-AMOUNT
           ELSE
               MOVE ZERO TO WS-DET-AMOUNT
           END-IF
           WRITE RPT-RECORD FROM WS-DETAIL.

       2500-CHECKPOINT.
           ADD 1 TO WS-CHKP-COUNT
           IF WS-CHKP-COUNT >= WS-CHKP-FREQ
               ADD 1 TO WS-CHKP-SEQ
               CALL 'CBLTDLI' USING DLI-CHKP
                                    CUST-PCB-LNK
                                    WS-CHKP-ID
               MOVE ZERO TO WS-CHKP-COUNT
               DISPLAY 'FNDTXFR: CHECKPOINT ' WS-CHKP-ID
                       ' AT RECORD ' WS-RECS-READ
           END-IF.

       3000-FINALIZE.
           CLOSE XFERIN
           CLOSE XFRRPT
           DISPLAY 'FNDTXFR: FUND TRANSFER BMP PROCESSING COMPLETE'
           DISPLAY 'TRANSFER REQUESTS READ: ' WS-RECS-READ
           DISPLAY 'TRANSFERS COMPLETED:    ' WS-XFR-PROCESSED
           DISPLAY 'TRNSEG PAIRS INSERTED:  ' WS-TRNS-INSERTED
           DISPLAY 'CUSTOMER NOT FOUND:     ' WS-CUST-NOT-FOUND
           DISPLAY 'INVALID INPUT:          ' WS-INVALID-INPUT
           DISPLAY 'DATABASE ERRORS:        ' WS-DB-ERRORS
           IF WS-DB-ERRORS > ZERO OR WS-INVALID-INPUT > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
