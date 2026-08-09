       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTMNT.
      *****************************************************************
      * ACCOUNT MAINTENANCE BATCH PROGRAM                            *
      * DESCRIPTION: Processes account maintenance transactions:     *
      *   - Interest rate changes for savings/CD accounts            *
      *   - Minimum balance fee assessment                           *
      *   - Account status updates (dormant flagging)                *
      *   - Monthly fee postings                                     *
      * INPUT:  PARMFILE  - Maintenance parameter cards (SYSIN)      *
      *         DB2 BANK.ACCOUNT table                               *
      * OUTPUT: ACCTMRPT  - Maintenance activity report              *
      *         DB2 BANK.ACCOUNT updated records                     *
      *         DB2 BANK.TRANSACTION_HIST fee/adj postings           *
      * CALLS:  ACCTVAL (Assembler) - account number validation      *
      *         DATAVAL (PL/I)      - data validation                *
      * DB2 PLAN: ACCTPLAN                                           *
      * FREQUENCY: Daily (rate changes on-demand)                   *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PARMFILE ASSIGN TO PARMCARD
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FILE-STATUS.

           SELECT ACCTMRPT ASSIGN TO ACCTMRPT
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FILE-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  PARMFILE
           RECORDING MODE IS V.
       01  PARM-RECORD               PIC X(80).

       FD  ACCTMRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD                PIC X(133).

       WORKING-STORAGE SECTION.
      *-----------------------------------------------------------------
      * DB2 COMMUNICATION AREA
      *-----------------------------------------------------------------
           EXEC SQL INCLUDE SQLCA END-EXEC.

      *-----------------------------------------------------------------
      * COPYBOOKS
      *-----------------------------------------------------------------
       COPY WSCOMMON.
       COPY ERRORCD.
       COPY ACCTMAST.

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES
      *-----------------------------------------------------------------
       01  WS-ACCT-HOST-VARS.
           05  HV-ACCT-NUMBER        PIC X(12).
           05  HV-ACCT-TYPE          PIC X(03).
           05  HV-ACCT-STATUS        PIC X(01).
           05  HV-CIF-NUMBER         PIC X(10).
           05  HV-INTEREST-RATE      PIC S9(3)V9(6) COMP-3.
           05  HV-CURRENT-BALANCE    PIC S9(13)V99  COMP-3.
           05  HV-AVAILABLE-BALANCE  PIC S9(13)V99  COMP-3.
           05  HV-LAST-ACTIVITY-DATE PIC X(10).
           05  HV-MONTHLY-FEE        PIC S9(5)V99   COMP-3.
           05  HV-MIN-BALANCE        PIC S9(9)V99   COMP-3.
           05  HV-LAST-UPDATE-USER   PIC X(08).
           05  HV-TRAN-ID            PIC X(16).
           05  HV-TRAN-CODE          PIC X(04).
           05  HV-TRAN-AMOUNT        PIC S9(13)V99  COMP-3.
           05  HV-TRAN-DESC          PIC X(40).
           05  HV-POST-DATE          PIC X(10).
           05  HV-NEW-RATE           PIC S9(3)V9(6) COMP-3.
           05  HV-RATE-IND           PIC X(01).
           05  HV-RATE-IND-IND       PIC S9(4) COMP.

      *-----------------------------------------------------------------
      * DECLARE DB2 CURSOR FOR ACCOUNT PROCESSING
      *-----------------------------------------------------------------
           EXEC SQL
               DECLARE ACCT_CURSOR CURSOR FOR
               SELECT ACCT_NUMBER,
                      ACCT_TYPE,
                      ACCT_STATUS,
                      CIF_NUMBER,
                      INTEREST_RATE,
                      CURRENT_BALANCE,
                      AVAILABLE_BALANCE,
                      LAST_ACTIVITY_DATE,
                      MONTHLY_FEE,
                      MIN_BALANCE
               FROM   BANK.ACCOUNT
               WHERE  ACCT_STATUS = 'O'
               FOR    UPDATE OF INTEREST_RATE,
                                ACCT_STATUS,
                                LAST_UPDATE_TS,
                                LAST_UPDATE_USER
           END-EXEC.

      *-----------------------------------------------------------------
      * PARAMETER CARD WORK AREAS
      *-----------------------------------------------------------------
       01  WS-PARM-RECORD.
           05  WS-PARM-FUNC          PIC X(04).
               88  PARM-RATE-CHG     VALUE 'RATE'.
               88  PARM-FEE-POST     VALUE 'FEES'.
               88  PARM-DORM-CHK     VALUE 'DORM'.
               88  PARM-ACCT-LOCK    VALUE 'LOCK'.
           05  FILLER                PIC X(01).
           05  WS-PARM-ACCT-TYPE    PIC X(03).
           05  FILLER                PIC X(01).
           05  WS-PARM-NEW-RATE     PIC 9(03)V9(6).
           05  FILLER                PIC X(01).
           05  WS-PARM-DORM-DAYS    PIC 9(04).
           05  FILLER                PIC X(01).
           05  WS-PARM-USER-ID      PIC X(08).
           05  FILLER                PIC X(49).

      *-----------------------------------------------------------------
      * VALIDATION INTERFACE TO PL/I DATAVAL
      *-----------------------------------------------------------------
       01  WS-VAL-PARMS.
           05  WS-VAL-FUNCTION       PIC X(02).
           05  WS-VAL-INPUT          PIC X(50).
           05  WS-VAL-FIELD-NAME     PIC X(20).
           05  WS-VAL-ERROR-CODE     PIC X(04).
           05  WS-VAL-ERROR-MSG      PIC X(80).
           05  WS-VAL-RETURN-CODE    PIC S9(4) COMP.

      *-----------------------------------------------------------------
      * ACCOUNT VALIDATION INTERFACE TO ASSEMBLER
      *-----------------------------------------------------------------
       01  WS-ACCTVAL-PARMS.
           05  WS-AV-FUNCTION        PIC X(01).
           05  WS-AV-ACCT-NUMBER     PIC X(12).
           05  WS-AV-ROUTING-NUM     PIC X(09).
           05  WS-AV-RESULT-CODE     PIC X(01).

      *-----------------------------------------------------------------
      * REPORT LINE AREAS
      *-----------------------------------------------------------------
       01  WS-RPT-HEADER.
           05  FILLER   PIC X(10) VALUE 'ACCOUNT   '.
           05  FILLER   PIC X(06) VALUE 'TYPE  '.
           05  FILLER   PIC X(15) VALUE 'BALANCE        '.
           05  FILLER   PIC X(15) VALUE 'OLD RATE       '.
           05  FILLER   PIC X(15) VALUE 'NEW RATE       '.
           05  FILLER   PIC X(15) VALUE 'ACTION         '.
           05  FILLER   PIC X(20) VALUE 'STATUS             '.

       01  WS-RPT-DETAIL.
           05  WS-RPT-ACCT          PIC X(12).
           05  FILLER               PIC X(01) VALUE SPACE.
           05  WS-RPT-TYPE          PIC X(03).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-RPT-BALANCE       PIC ZZZ,ZZZ,ZZZ,ZZ9.99-.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-RPT-OLD-RATE      PIC Z9.999999.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-RPT-NEW-RATE      PIC Z9.999999.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-RPT-ACTION        PIC X(15).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-RPT-STATUS        PIC X(15).

      *-----------------------------------------------------------------
      * PROCESSING COUNTERS
      *-----------------------------------------------------------------
       01  WS-COUNTERS.
           05  WS-ACCTS-READ        PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-RATES-CHANGED     PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-FEES-POSTED       PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-DORM-FLAGGED      PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-ERRORS            PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-COMMITS           PIC 9(05) COMP-3 VALUE ZERO.

       01  WS-TRAN-ID-SEED          PIC 9(16) COMP VALUE ZERO.
       01  WS-FILE-STATUS           PIC X(02).
           88  WS-FILE-OK           VALUE '00'.
           88  WS-FILE-EOF          VALUE '10'.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS-PARM-CARDS
               UNTIL WS-EOF
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'ACCTMNT: ACCOUNT MAINTENANCE STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE
                  WS-CURRENT-MONTH DELIMITED BY SIZE
                  WS-CURRENT-DAY   DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           OPEN INPUT  PARMFILE
           OPEN OUTPUT ACCTMRPT

           IF NOT WS-FILE-OK
               DISPLAY 'ACCTMNT: ERROR OPENING FILES - STATUS='
                       WS-FILE-STATUS
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF

           WRITE RPT-RECORD FROM WS-RPT-HEADER
           PERFORM 1100-READ-PARM-CARD.

       1100-READ-PARM-CARD.
           READ PARMFILE INTO WS-PARM-RECORD
               AT END
                   SET WS-EOF TO TRUE
           END-READ.

       2000-PROCESS-PARM-CARDS.
           ADD 1 TO WS-RECORD-COUNT

           EVALUATE TRUE
               WHEN PARM-RATE-CHG
                   PERFORM 2100-PROCESS-RATE-CHANGE
               WHEN PARM-FEE-POST
                   PERFORM 2200-PROCESS-FEE-POSTING THRU 2290-FEE-DONE
               WHEN PARM-DORM-CHK
                   PERFORM 2300-PROCESS-DORMANCY-CHECK
               WHEN OTHER
                   DISPLAY 'ACCTMNT: INVALID PARM FUNCTION '
                           WS-PARM-FUNC ' AT RECORD '
                           WS-RECORD-COUNT
                   ADD 1 TO WS-ERRORS
           END-EVALUATE
           PERFORM 1100-READ-PARM-CARD.

      *-----------------------------------------------------------------
      * 2100 - PROCESS INTEREST RATE CHANGE
      *-----------------------------------------------------------------
       2100-PROCESS-RATE-CHANGE.
           DISPLAY 'ACCTMNT: PROCESSING RATE CHANGE FOR '
                   WS-PARM-ACCT-TYPE ' RATE=' WS-PARM-NEW-RATE

           MOVE WS-PARM-NEW-RATE TO HV-NEW-RATE
           MOVE WS-PARM-ACCT-TYPE TO HV-ACCT-TYPE
           MOVE WS-PARM-USER-ID TO HV-LAST-UPDATE-USER

           EXEC SQL
               UPDATE BANK.ACCOUNT
               SET    INTEREST_RATE    = :HV-NEW-RATE,
                      LAST_UPDATE_TS   = CURRENT TIMESTAMP,
                      LAST_UPDATE_USER = :HV-LAST-UPDATE-USER
               WHERE  ACCT_TYPE        = :HV-ACCT-TYPE
               AND    ACCT_STATUS      = 'O'
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   DISPLAY 'ACCTMNT: RATE UPDATE SUCCESSFUL. '
                           'ROWS=' SQLERRD(3)
                   ADD SQLERRD(3) TO WS-RATES-CHANGED
                   EXEC SQL COMMIT END-EXEC
               WHEN OTHER
                   DISPLAY 'ACCTMNT: DB2 ERROR ON RATE UPDATE '
                           'SQLCODE=' SQLCODE
                   ADD 1 TO WS-ERRORS
                   EXEC SQL ROLLBACK END-EXEC
           END-EVALUATE.

      *-----------------------------------------------------------------
      * 2200 - PROCESS MONTHLY FEE ASSESSMENT
      *-----------------------------------------------------------------
       2200-PROCESS-FEE-POSTING.
           DISPLAY 'ACCTMNT: OPENING CURSOR FOR FEE ASSESSMENT'

           EXEC SQL OPEN ACCT_CURSOR END-EXEC

           IF SQLCODE NOT = 0
               DISPLAY 'ACCTMNT: ERROR OPENING ACCT_CURSOR SQLCODE='
                       SQLCODE
               ADD 1 TO WS-ERRORS
               GO TO 2290-FEE-DONE
           END-IF

           PERFORM 2210-FETCH-AND-ASSESS-FEE
               UNTIL SQLCODE = +100.

       2290-FEE-DONE.
           EXEC SQL CLOSE ACCT_CURSOR END-EXEC.

       2210-FETCH-AND-ASSESS-FEE.
           EXEC SQL
               FETCH ACCT_CURSOR
               INTO  :HV-ACCT-NUMBER,
                     :HV-ACCT-TYPE,
                     :HV-ACCT-STATUS,
                     :HV-CIF-NUMBER,
                     :HV-INTEREST-RATE,
                     :HV-CURRENT-BALANCE,
                     :HV-AVAILABLE-BALANCE,
                     :HV-LAST-ACTIVITY-DATE,
                     :HV-MONTHLY-FEE,
                     :HV-MIN-BALANCE
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   ADD 1 TO WS-ACCTS-READ
                   PERFORM 2220-ASSESS-FEE-IF-BELOW-MIN
               WHEN +100
                   CONTINUE
               WHEN OTHER
                   DISPLAY 'ACCTMNT: FETCH ERROR SQLCODE=' SQLCODE
                   ADD 1 TO WS-ERRORS
                   MOVE +100 TO SQLCODE
           END-EVALUATE.

       2220-ASSESS-FEE-IF-BELOW-MIN.
           IF HV-CURRENT-BALANCE < HV-MIN-BALANCE
           AND HV-MONTHLY-FEE > ZERO
               PERFORM 2230-POST-FEE-TRANSACTION
           END-IF.

       2230-POST-FEE-TRANSACTION.
           ADD 1 TO WS-TRAN-ID-SEED
           MOVE WS-TRAN-ID-SEED    TO HV-TRAN-ID
           MOVE 'FEE ' TO HV-TRAN-CODE
           MOVE HV-MONTHLY-FEE     TO HV-TRAN-AMOUNT
           MOVE WS-BUSINESS-DATE   TO HV-POST-DATE
           MOVE 'MONTHLY MAINTENANCE FEE' TO HV-TRAN-DESC

           EXEC SQL
               INSERT INTO BANK.TRANSACTION_HIST
                      (TRAN_ID, ACCT_NUMBER, TRAN_TYPE, TRAN_CODE,
                       AMOUNT, EFFECTIVE_DATE, POST_DATE,
                       DESCRIPTION, CHANNEL, TRAN_STATUS)
               VALUES (:HV-TRAN-ID, :HV-ACCT-NUMBER, 'DR',
                       :HV-TRAN-CODE, :HV-TRAN-AMOUNT,
                       :HV-POST-DATE, :HV-POST-DATE,
                       :HV-TRAN-DESC, 'BAT', 'P')
           END-EXEC

           IF SQLCODE = 0
               SUBTRACT HV-MONTHLY-FEE FROM HV-CURRENT-BALANCE
               SUBTRACT HV-MONTHLY-FEE FROM HV-AVAILABLE-BALANCE
               EXEC SQL
                   UPDATE BANK.ACCOUNT
                   SET    CURRENT_BALANCE   = :HV-CURRENT-BALANCE,
                          AVAILABLE_BALANCE = :HV-AVAILABLE-BALANCE,
                          LAST_UPDATE_TS    = CURRENT TIMESTAMP,
                          LAST_UPDATE_USER  = 'ACCTMNT'
                   WHERE CURRENT OF ACCT_CURSOR
               END-EXEC

               IF SQLCODE = 0
                   ADD 1 TO WS-FEES-POSTED
                   ADD 1 TO WS-COMMIT-COUNT

                   IF WS-COMMIT-COUNT >= WS-COMMIT-FREQ
                       EXEC SQL COMMIT END-EXEC
                       ADD 1 TO WS-COMMITS
                       MOVE ZERO TO WS-COMMIT-COUNT
                   END-IF

                   MOVE HV-ACCT-NUMBER TO WS-RPT-ACCT
                   MOVE HV-ACCT-TYPE   TO WS-RPT-TYPE
                   MOVE HV-CURRENT-BALANCE TO WS-RPT-BALANCE
                   MOVE 'FEE POSTED' TO WS-RPT-ACTION
                   WRITE RPT-RECORD FROM WS-RPT-DETAIL
               ELSE
                   DISPLAY 'ACCTMNT: ERROR UPDATING BALANCE '
                           'ACCT=' HV-ACCT-NUMBER
                           ' SQLCODE=' SQLCODE
                   ADD 1 TO WS-ERRORS
               END-IF
           ELSE
               DISPLAY 'ACCTMNT: ERROR INSERTING FEE TRAN '
                       'ACCT=' HV-ACCT-NUMBER
                       ' SQLCODE=' SQLCODE
               ADD 1 TO WS-ERRORS
           END-IF.

      *-----------------------------------------------------------------
      * 2300 - PROCESS DORMANCY CHECK
      *-----------------------------------------------------------------
       2300-PROCESS-DORMANCY-CHECK.
           DISPLAY 'ACCTMNT: PROCESSING DORMANCY - DAYS='
               WS-PARM-DORM-DAYS

           EXEC SQL
               UPDATE BANK.ACCOUNT
               SET    ACCT_STATUS      = 'D',
                      LAST_UPDATE_TS   = CURRENT TIMESTAMP,
                      LAST_UPDATE_USER = 'ACCTMNT'
               WHERE  ACCT_STATUS = 'O'
               AND    LAST_ACTIVITY_DATE < (CURRENT DATE -
                      :WS-PARM-DORM-DAYS DAYS)
               AND    ACCT_TYPE   IN ('CHK','SAV','MMA')
           END-EXEC

           IF SQLCODE = 0
               ADD SQLERRD(3) TO WS-DORM-FLAGGED
               DISPLAY 'ACCTMNT: DORMANT ACCOUNTS FLAGGED=' SQLERRD(3)
               EXEC SQL COMMIT END-EXEC
           ELSE
               DISPLAY 'ACCTMNT: DORMANCY UPDATE ERROR SQLCODE=' SQLCODE
               ADD 1 TO WS-ERRORS
               EXEC SQL ROLLBACK END-EXEC
           END-IF.

       3000-FINALIZE.
           EXEC SQL COMMIT END-EXEC

           CLOSE PARMFILE
           CLOSE ACCTMRPT

           DISPLAY 'ACCTMNT: PROCESSING COMPLETE'
           DISPLAY 'ACCOUNTS READ:      ' WS-ACCTS-READ
           DISPLAY 'RATES CHANGED:      ' WS-RATES-CHANGED
           DISPLAY 'FEES POSTED:        ' WS-FEES-POSTED
           DISPLAY 'DORMANT FLAGGED:    ' WS-DORM-FLAGGED
           DISPLAY 'ERRORS:             ' WS-ERRORS
           DISPLAY 'COMMITS ISSUED:     ' WS-COMMITS

           IF WS-ERRORS > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
