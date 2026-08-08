       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEPTBMP.
      *****************************************************************
      * DEPOSIT BATCH - IMS BMP (BATCH MESSAGE PROCESSING PROGRAM)  *
      * DESCRIPTION: Reads deposit/withdrawal records from the       *
      *   DEPTIN sequential file and inserts a TRNSEG child under   *
      *   CUSTSEG in CUSTDB for each valid record. Checkpoints      *
      *   every WS-CHKP-FREQ records to support IMS restart.        *
      * INPUT:  DEPTIN - sequential deposit records (50 bytes each) *
      *         CUSTDB - CUSTSEG root for key validation            *
      * OUTPUT: DEPTBMP inserts TRNSEG segments into CUSTDB         *
      *         DEPTRPT - deposit processing summary report         *
      * ENTRY:  DLITCBL (IMS standard COBOL PCB entry point)       *
      * PCBs:   CUST-PCB (CUSTDB - no IOPCB, file-driven BMP)     *
      * PSB:    DEPTBPSB                                            *
      * PROC:   IMSBTCH (PROG=DEPTBMP,PSB=DEPTBPSB)               *
      * FREQUENCY: On-demand (submitted via DEPTJOB.jcl)           *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DEPTIN  ASSIGN TO DEPTIN
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-DEPTIN-STATUS.
           SELECT DEPTRPT ASSIGN TO DEPTRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  DEPTIN
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  BATCH-DEPOSIT-REC.
           05  BATCH-CIF-NUMBER     PIC X(10).
           05  BATCH-ACCT-NUMBER    PIC X(12).
           05  BATCH-AMOUNT-CHAR    PIC X(15).
           05  BATCH-TRAN-TYPE      PIC X(02).
           05  BATCH-FILLER         PIC X(11).

       FD  DEPTRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD               PIC X(133).

       WORKING-STORAGE SECTION.
           COPY WSCOMMON.
           COPY ERRORCD.
           COPY IMSPCB.
           COPY TRNSEG.

       01  WS-DEPTIN-STATUS         PIC X(02).
           88  WS-DEPTIN-OK         VALUE '00'.
           88  WS-DEPTIN-EOF        VALUE '10'.

       01  WS-EDIT-WORK.
           05  WS-AMOUNT-WORK       PIC S9(11)V99.
           05  WS-AMOUNT-DISP       PIC ZZZ,ZZZ,ZZZ.99.

       01  WS-CHKP-FREQ             PIC 9(05) COMP-3 VALUE 500.
       01  WS-CHKP-COUNT            PIC 9(05) COMP-3 VALUE ZERO.
       01  WS-CHKP-ID.
           05  FILLER               PIC X(04) VALUE 'DEPT'.
           05  WS-CHKP-SEQ          PIC 9(04).

       01  WS-RECORD-ERROR          PIC X(01) VALUE 'N'.
           88  RECORD-ERROR-FOUND   VALUE 'Y'.
           88  RECORD-OK            VALUE 'N'.

       01  WS-HDR.
           05  FILLER PIC X(15) VALUE 'CIF            '.
           05  FILLER PIC X(15) VALUE 'ACCOUNT        '.
           05  FILLER PIC X(05) VALUE 'TYPE '.
           05  FILLER PIC X(20) VALUE '              AMOUNT'.
           05  FILLER PIC X(10) VALUE '  STATUS  '.

       01  WS-DETAIL.
           05  WS-DET-CIF           PIC X(10).
           05  FILLER               PIC X(05) VALUE SPACES.
           05  WS-DET-ACCT          PIC X(12).
           05  FILLER               PIC X(03) VALUE SPACES.
           05  WS-DET-TYPE          PIC X(02).
           05  FILLER               PIC X(03) VALUE SPACES.
           05  WS-DET-AMOUNT        PIC ZZZ,ZZZ,ZZZ.99.
           05  FILLER               PIC X(03) VALUE SPACES.
           05  WS-DET-STATUS        PIC X(12).

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
           PERFORM 2000-PROCESS-DEPOSITS
               UNTIL WS-EOF
           PERFORM 3000-FINALIZE
           GOBACK.

       1000-INITIALIZE.
           DISPLAY 'DEPTBMP: BMP DEPOSIT BATCH PROCESSING STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR  DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-MONTH DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-DAY   DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING
           MOVE ZERO TO WS-CHKP-SEQ
           OPEN INPUT  DEPTIN
           OPEN OUTPUT DEPTRPT
           WRITE RPT-RECORD FROM WS-HDR

      *    INITIAL CHECKPOINT TO REGISTER PROGRAM WITH IMS RESTART
           ADD 1 TO WS-CHKP-SEQ
           CALL 'CBLTDLI' USING DLI-CHKP
                                CUST-PCB-LNK
                                WS-CHKP-ID

           READ DEPTIN
               AT END SET WS-EOF TO TRUE
           END-READ.

       2000-PROCESS-DEPOSITS.
           MOVE 'N' TO WS-RECORD-ERROR
           ADD 1 TO WS-RECS-READ
           PERFORM 2100-VALIDATE-RECORD
           IF RECORD-OK
               PERFORM 2200-GET-CUSTOMER
           END-IF
           IF RECORD-OK
               PERFORM 2300-INSERT-TRNSEG
           END-IF
           PERFORM 2400-WRITE-DETAIL
           PERFORM 2500-CHECKPOINT
           READ DEPTIN
               AT END SET WS-EOF TO TRUE
           END-READ.

       2100-VALIDATE-RECORD.
           IF BATCH-CIF-NUMBER = SPACES OR LOW-VALUES
               MOVE 'CIF REQUIRED  ' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           IF BATCH-TRAN-TYPE NOT = 'DP' AND NOT = 'WD'
               MOVE 'BAD TRAN TYPE ' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           IF FUNCTION TEST-NUMVAL(BATCH-AMOUNT-CHAR) NOT = ZERO
               MOVE 'BAD AMOUNT    ' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           COMPUTE WS-AMOUNT-WORK =
               FUNCTION NUMVAL(BATCH-AMOUNT-CHAR)
           IF WS-AMOUNT-WORK <= ZERO
               MOVE 'AMOUNT LE ZERO' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
           END-IF.

       2200-GET-CUSTOMER.
      *    GU ON CUST-PCB ESTABLISHES POSITION AT THE PARENT CUSTSEG
      *    BEFORE ISRT OF THE TRNSEG CHILD BELOW
           MOVE BATCH-CIF-NUMBER TO SSA-CUST-KEY-VALUE
           CALL 'CBLTDLI' USING DLI-GU
                                CUST-PCB-LNK
                                IMS-IO-AREA
                                SSA-CUSTOMER
           EVALUATE CUST-STATUS
               WHEN '  '
                   CONTINUE
               WHEN 'GE'
                   MOVE 'CUST NOT FOUND' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-CUST-NOT-FOUND
               WHEN OTHER
                   MOVE 'DB ERROR CUST ' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-DB-ERRORS
                   DISPLAY 'DEPTBMP: CUSTDB GU ERROR STATUS='
                           CUST-STATUS
                           ' CIF=' BATCH-CIF-NUMBER
           END-EVALUATE.

       2300-INSERT-TRNSEG.
      *    ISRT INSERTS TRNSEG AS CHILD OF POSITIONED CUSTSEG.
      *    QUALIFIED SSA-CUSTOMER PLUS UNQUALIFIED SSA-UNQUAL-TRAN
      *    GIVES IMS THE FULL HIERARCHICAL PATH FOR THE INSERT.
           MOVE SPACES                TO TRNSEG-IO
           MOVE BATCH-CIF-NUMBER      TO TRAN-CIF-NUMBER
           MOVE BATCH-ACCT-NUMBER     TO TRAN-ACCT-NUMBER
           MOVE WS-AMOUNT-WORK        TO TRAN-AMOUNT
           MOVE BATCH-TRAN-TYPE       TO TRAN-TYPE
           MOVE WS-BUSINESS-DATE      TO TRAN-DATE
           MOVE 'BATC'                TO TRAN-CHANNEL
           MOVE 'P'                   TO TRAN-STATUS
           MOVE FUNCTION CURRENT-DATE TO TRAN-TIMESTAMP

           CALL 'CBLTDLI' USING DLI-ISRT
                                CUST-PCB-LNK
                                TRNSEG-IO
                                SSA-CUSTOMER
                                SSA-UNQUAL-TRAN
           EVALUATE CUST-STATUS
               WHEN '  '
                   ADD 1 TO WS-TRNS-INSERTED
                   MOVE 'POSTED      ' TO WS-DET-STATUS
               WHEN OTHER
                   MOVE 'DB ERROR ISRT' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-DB-ERRORS
                   DISPLAY 'DEPTBMP: TRNSEG ISRT ERROR STATUS='
                           CUST-STATUS
                           ' CIF=' BATCH-CIF-NUMBER
           END-EVALUATE.

       2400-WRITE-DETAIL.
           MOVE BATCH-CIF-NUMBER  TO WS-DET-CIF
           MOVE BATCH-ACCT-NUMBER TO WS-DET-ACCT
           MOVE BATCH-TRAN-TYPE   TO WS-DET-TYPE
           IF WS-AMOUNT-WORK > ZERO
               MOVE WS-AMOUNT-WORK TO WS-DET-AMOUNT
           ELSE
               MOVE ZERO TO WS-DET-AMOUNT
           END-IF
           WRITE RPT-RECORD FROM WS-DETAIL.

       2500-CHECKPOINT.
      *    PERIODIC CHKP CALL LETS IMS SAVE RESTART INFORMATION.
      *    ON FAILURE THE JOB CAN BE RESTARTED FROM THE LAST CHECKPOINT
      *    INSTEAD OF REPROCESSING THE ENTIRE INPUT FILE FROM THE TOP.
           ADD 1 TO WS-CHKP-COUNT
           IF WS-CHKP-COUNT >= WS-CHKP-FREQ
               ADD 1 TO WS-CHKP-SEQ
               CALL 'CBLTDLI' USING DLI-CHKP
                                    CUST-PCB-LNK
                                    WS-CHKP-ID
               MOVE ZERO TO WS-CHKP-COUNT
               DISPLAY 'DEPTBMP: CHECKPOINT ' WS-CHKP-ID
                       ' AT RECORD ' WS-RECS-READ
           END-IF.

       3000-FINALIZE.
           CLOSE DEPTIN
           CLOSE DEPTRPT
           DISPLAY 'DEPTBMP: BMP DEPOSIT BATCH PROCESSING COMPLETE'
           DISPLAY 'RECORDS READ:        ' WS-RECS-READ
           DISPLAY 'SEGMENTS INSERTED:   ' WS-TRNS-INSERTED
           DISPLAY 'CUSTOMER NOT FOUND:  ' WS-CUST-NOT-FOUND
           DISPLAY 'INVALID INPUT:       ' WS-INVALID-INPUT
           DISPLAY 'DATABASE ERRORS:     ' WS-DB-ERRORS
           IF WS-DB-ERRORS > ZERO OR WS-INVALID-INPUT > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
