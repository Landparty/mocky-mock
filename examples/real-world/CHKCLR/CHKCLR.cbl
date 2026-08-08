       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHKCLR.
      *****************************************************************
      * CHECK CLEARING BATCH PROGRAM                                 *
      * DESCRIPTION: Processes check clearing items received from    *
      *   the Federal Reserve or correspondent banks. Validates      *
      *   account, verifies funds availability, posts debit entries, *
      *   handles NSF returns and stop payments.                     *
      * INPUT:  CHKFILE   - Check clearing input file (sorted)       *
      *         STOPPAY   - Stop payment file (VSAM)                 *
      * OUTPUT: CHKRETURNS - Return items (NSF, stop pay, closed)    *
      *         CHKRPT    - Check clearing run report                *
      *         DB2 BANK.TRANSACTION_HIST (cleared items)            *
      * CALLS:  ACCTVAL (Assembler) - account validation             *
      * DB2 PLAN: ACCTPLAN                                           *
      * FREQUENCY: Multiple times daily (Fed clearing windows)       *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CHKFILE ASSIGN TO CHKFILE
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-CHK-STATUS.

           SELECT STOPPAY ASSIGN TO STOPPAY
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS SP-KEY
               FILE STATUS IS WS-SP-STATUS.

           SELECT CHKRETURNS ASSIGN TO CHKRETURN
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-RET-STATUS.

           SELECT CHKRPT ASSIGN TO CHKRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  CHKFILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  CHK-INPUT-RECORD.
           05  CHK-ROUTING-NUMBER    PIC X(09).
           05  CHK-ACCT-NUMBER       PIC X(12).
           05  CHK-CHECK-NUMBER      PIC X(10).
           05  CHK-AMOUNT            PIC S9(09)V99 COMP-3.
           05  CHK-DATE              PIC X(10).
           05  CHK-SEQ-NUMBER        PIC X(08).
           05  FILLER                PIC X(10).

       FD  STOPPAY
           RECORDING MODE IS F.
       01  STOP-PAY-RECORD.
           05  SP-KEY.
               10  SP-ACCT-NUMBER    PIC X(12).
               10  SP-CHECK-NUMBER   PIC X(10).
           05  SP-AMOUNT             PIC S9(09)V99 COMP-3.
           05  SP-DATE-ISSUED        PIC X(10).
           05  SP-EXPIRY-DATE        PIC X(10).

       FD  CHKRETURNS
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RETURN-RECORD.
           05  RET-ROUTING-NUMBER    PIC X(09).
           05  RET-ACCT-NUMBER       PIC X(12).
           05  RET-CHECK-NUMBER      PIC X(10).
           05  RET-AMOUNT            PIC S9(09)V99 COMP-3.
           05  RET-DATE              PIC X(10).
           05  RET-REASON-CODE       PIC X(03).
           05  RET-SEQ-NUMBER        PIC X(08).
           05  FILLER                PIC X(10).

       FD  CHKRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD                PIC X(133).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

       COPY WSCOMMON.
       COPY ERRORCD.

       01  WS-CHK-STATUS             PIC X(02).
           88  WS-CHK-OK             VALUE '00'.
           88  WS-CHK-STATUS-EOF     VALUE '10'.
       01  WS-SP-STATUS              PIC X(02).
           88  WS-SP-OK              VALUE '00'.
           88  WS-SP-NOT-FOUND       VALUE '23'.
       01  WS-RET-STATUS             PIC X(02).

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES
      *-----------------------------------------------------------------
       01  WS-CHK-HV.
           05  HV-ACCT-NUMBER        PIC X(12).
           05  HV-ACCT-STATUS        PIC X(01).
           05  HV-CURRENT-BALANCE    PIC S9(13)V99 COMP-3.
           05  HV-AVAILABLE-BALANCE  PIC S9(13)V99 COMP-3.
           05  HV-TRAN-ID            PIC X(16).
           05  HV-TRAN-AMOUNT        PIC S9(13)V99 COMP-3.
           05  HV-POST-DATE          PIC X(10).
           05  HV-CHECK-NUM          PIC X(10).

      *-----------------------------------------------------------------
      * ACCOUNT VALIDATION PARMS
      *-----------------------------------------------------------------
       01  WS-ACCTVAL-PARMS.
           05  WS-AV-FUNCTION        PIC X(01).
           05  WS-AV-ACCT-NUMBER     PIC X(12).
           05  WS-AV-ROUTING-NUM     PIC X(09).
           05  WS-AV-RESULT-CODE     PIC X(01).

       01  WS-RETURN-REASON          PIC X(03).
       01  WS-TRAN-SEED              PIC 9(16) COMP VALUE ZERO.
       01  WS-CHK-EOF               PIC X(01) VALUE 'N'.
           88  WS-CHK-FILE-EOF      VALUE 'Y'.

      *-----------------------------------------------------------------
      * REPORT LINE
      *-----------------------------------------------------------------
       01  WS-CHK-HDR.
           05  FILLER PIC X(10) VALUE 'ACCOUNT   '.
           05  FILLER PIC X(12) VALUE 'CHECK NUM   '.
           05  FILLER PIC X(15) VALUE '         AMOUNT'.
           05  FILLER PIC X(12) VALUE 'STATUS      '.
           05  FILLER PIC X(10) VALUE 'RETURN CD '.

       01  WS-CHK-DETAIL.
           05  WS-CD-ACCT           PIC X(12).
           05  FILLER               PIC X(01) VALUE SPACE.
           05  WS-CD-CHECKNUM       PIC X(10).
           05  FILLER               PIC X(01) VALUE SPACE.
           05  WS-CD-AMOUNT         PIC ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-CD-STATUS         PIC X(10).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-CD-RETURN         PIC X(06).

      *-----------------------------------------------------------------
      * COUNTERS
      *-----------------------------------------------------------------
       01  WS-CHK-CNTS.
           05  WS-ITEMS-READ        PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-ITEMS-CLEARED     PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-ITEMS-NSF         PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-ITEMS-STOPPED     PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-ITEMS-CLOSED      PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-ROUTING-INVALID   PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-TOTAL-CLEARED     PIC S9(15)V99 COMP-3 VALUE ZERO.
           05  WS-CHK-ERRORS        PIC 9(05) COMP-3 VALUE ZERO.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS-CHECKS
               UNTIL WS-CHK-FILE-EOF
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'CHKCLR: CHECK CLEARING PROCESSING STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE '-'
                  DELIMITED BY SIZE WS-CURRENT-MONTH
                  DELIMITED BY SIZE '-' DELIMITED BY SIZE
                  WS-CURRENT-DAY DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           OPEN INPUT  CHKFILE
           OPEN INPUT  STOPPAY
           OPEN OUTPUT CHKRETURNS
           OPEN OUTPUT CHKRPT

           WRITE RPT-RECORD FROM WS-CHK-HDR
           PERFORM 1100-READ-CHECK.

       1100-READ-CHECK.
           READ CHKFILE
               AT END SET WS-CHK-FILE-EOF TO TRUE
           END-READ.

       2000-PROCESS-CHECKS.
           ADD 1 TO WS-ITEMS-READ

      *    VALIDATE ROUTING NUMBER
           MOVE 'R'                TO WS-AV-FUNCTION
           MOVE CHK-ROUTING-NUMBER TO WS-AV-ROUTING-NUM
           CALL 'ACCTVAL' USING WS-ACCTVAL-PARMS

           IF WS-AV-RESULT-CODE NOT = 'V'
               MOVE 'R06' TO WS-RETURN-REASON
               ADD 1 TO WS-ROUTING-INVALID
               PERFORM 2800-WRITE-RETURN
               PERFORM 1100-READ-CHECK
               GO TO 2000-EXIT
           END-IF

      *    LOOK UP ACCOUNT
           MOVE CHK-ACCT-NUMBER TO HV-ACCT-NUMBER
           EXEC SQL
               SELECT ACCT_STATUS,
                      CURRENT_BALANCE,
                      AVAILABLE_BALANCE
               INTO   :HV-ACCT-STATUS,
                      :HV-CURRENT-BALANCE,
                      :HV-AVAILABLE-BALANCE
               FROM   BANK.ACCOUNT
               WHERE  ACCT_NUMBER = :HV-ACCT-NUMBER
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   CONTINUE
               WHEN +100
                   MOVE 'R03' TO WS-RETURN-REASON
                   ADD 1 TO WS-ITEMS-CLOSED
                   PERFORM 2800-WRITE-RETURN
                   PERFORM 1100-READ-CHECK
                   GO TO 2000-EXIT
               WHEN OTHER
                   ADD 1 TO WS-CHK-ERRORS
                   PERFORM 1100-READ-CHECK
                   GO TO 2000-EXIT
           END-EVALUATE

      *    CHECK ACCOUNT STATUS
           IF HV-ACCT-STATUS = 'C'
               MOVE 'R02' TO WS-RETURN-REASON
               ADD 1 TO WS-ITEMS-CLOSED
               PERFORM 2800-WRITE-RETURN
               PERFORM 1100-READ-CHECK
               GO TO 2000-EXIT
           END-IF

      *    CHECK STOP PAYMENT FILE
           MOVE CHK-ACCT-NUMBER  TO SP-ACCT-NUMBER
           MOVE CHK-CHECK-NUMBER TO SP-CHECK-NUMBER
           READ STOPPAY
               INVALID KEY CONTINUE
           END-READ
           IF WS-SP-OK
               MOVE 'R08' TO WS-RETURN-REASON
               ADD 1 TO WS-ITEMS-STOPPED
               PERFORM 2800-WRITE-RETURN
               PERFORM 1100-READ-CHECK
               GO TO 2000-EXIT
           END-IF

      *    CHECK FUNDS AVAILABILITY
           MOVE CHK-AMOUNT TO HV-TRAN-AMOUNT
           IF HV-AVAILABLE-BALANCE < HV-TRAN-AMOUNT
               MOVE 'R01' TO WS-RETURN-REASON
               ADD 1 TO WS-ITEMS-NSF
               PERFORM 2800-WRITE-RETURN
               PERFORM 1100-READ-CHECK
               GO TO 2000-EXIT
           END-IF

      *    POST THE CHECK CLEARING DEBIT
           SUBTRACT HV-TRAN-AMOUNT FROM HV-CURRENT-BALANCE
           SUBTRACT HV-TRAN-AMOUNT FROM HV-AVAILABLE-BALANCE

           ADD 1 TO WS-TRAN-SEED
           MOVE WS-TRAN-SEED     TO HV-TRAN-ID
           MOVE CHK-CHECK-NUMBER TO HV-CHECK-NUM
           MOVE WS-BUSINESS-DATE TO HV-POST-DATE

           EXEC SQL
               INSERT INTO BANK.TRANSACTION_HIST
                      (TRAN_ID, ACCT_NUMBER, TRAN_TYPE, TRAN_CODE,
                       AMOUNT, EFFECTIVE_DATE, POST_DATE,
                       DESCRIPTION, CHECK_NUMBER, CHANNEL, TRAN_STATUS)
               VALUES (:HV-TRAN-ID, :HV-ACCT-NUMBER, 'DR', 'CHK ',
                       :HV-TRAN-AMOUNT, :CHK-DATE, :HV-POST-DATE,
                       'CHECK CLEARING', :HV-CHECK-NUM, 'BAT', 'P')
           END-EXEC

           IF SQLCODE = 0
               EXEC SQL
                   UPDATE BANK.ACCOUNT
                   SET    CURRENT_BALANCE    = :HV-CURRENT-BALANCE,
                          AVAILABLE_BALANCE  = :HV-AVAILABLE-BALANCE,
                          LAST_ACTIVITY_DATE = :HV-POST-DATE,
                          LAST_UPDATE_TS     = CURRENT TIMESTAMP,
                          LAST_UPDATE_USER   = 'CHKCLR'
                   WHERE  ACCT_NUMBER = :HV-ACCT-NUMBER
               END-EXEC

               ADD 1 TO WS-ITEMS-CLEARED
               ADD HV-TRAN-AMOUNT TO WS-TOTAL-CLEARED
               ADD 1 TO WS-COMMIT-COUNT
               IF WS-COMMIT-COUNT >= WS-COMMIT-FREQ
                   EXEC SQL COMMIT END-EXEC
                   MOVE ZERO TO WS-COMMIT-COUNT
               END-IF
           ELSE
               ADD 1 TO WS-CHK-ERRORS
               EXEC SQL ROLLBACK END-EXEC
           END-IF

           MOVE CHK-ACCT-NUMBER  TO WS-CD-ACCT
           MOVE CHK-CHECK-NUMBER TO WS-CD-CHECKNUM
           MOVE CHK-AMOUNT       TO WS-CD-AMOUNT
           MOVE 'CLEARED'        TO WS-CD-STATUS
           MOVE SPACES           TO WS-CD-RETURN
           WRITE RPT-RECORD FROM WS-CHK-DETAIL.

       2000-EXIT.
           PERFORM 1100-READ-CHECK.

       2800-WRITE-RETURN.
           MOVE CHK-ROUTING-NUMBER TO RET-ROUTING-NUMBER
           MOVE CHK-ACCT-NUMBER    TO RET-ACCT-NUMBER
           MOVE CHK-CHECK-NUMBER   TO RET-CHECK-NUMBER
           MOVE CHK-AMOUNT         TO RET-AMOUNT
           MOVE WS-BUSINESS-DATE   TO RET-DATE
           MOVE WS-RETURN-REASON   TO RET-REASON-CODE
           MOVE CHK-SEQ-NUMBER     TO RET-SEQ-NUMBER
           WRITE RETURN-RECORD

           MOVE CHK-ACCT-NUMBER    TO WS-CD-ACCT
           MOVE CHK-CHECK-NUMBER   TO WS-CD-CHECKNUM
           MOVE CHK-AMOUNT         TO WS-CD-AMOUNT
           MOVE 'RETURNED'         TO WS-CD-STATUS
           MOVE WS-RETURN-REASON   TO WS-CD-RETURN
           WRITE RPT-RECORD FROM WS-CHK-DETAIL.

       3000-FINALIZE.
           EXEC SQL COMMIT END-EXEC

           CLOSE CHKFILE STOPPAY CHKRETURNS CHKRPT

           DISPLAY 'CHKCLR: CHECK CLEARING PROCESSING COMPLETE'
           DISPLAY 'ITEMS READ:           ' WS-ITEMS-READ
           DISPLAY 'ITEMS CLEARED:        ' WS-ITEMS-CLEARED
           DISPLAY 'NSF RETURNS:          ' WS-ITEMS-NSF
           DISPLAY 'STOP PAY RETURNS:     ' WS-ITEMS-STOPPED
           DISPLAY 'CLOSED ACCT RETURNS:  ' WS-ITEMS-CLOSED
           DISPLAY 'ROUTING INVALID:      ' WS-ROUTING-INVALID
           DISPLAY 'TOTAL CLEARED:        ' WS-TOTAL-CLEARED
           DISPLAY 'ERRORS:               ' WS-CHK-ERRORS

           IF WS-CHK-ERRORS > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
