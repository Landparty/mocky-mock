       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTCALC.
      *****************************************************************
      * INTEREST CALCULATION BATCH PROGRAM                           *
      * DESCRIPTION: Calculates and posts daily interest accruals    *
      *   for all open savings, money market, CD, and IRA accounts.  *
      *   Also applies monthly interest payments to accounts.        *
      * INPUT:  DB2 BANK.ACCOUNT (all interest-bearing accounts)     *
      *         DB2 BANK.DAILY_BALANCE (prior day balances)          *
      * OUTPUT: DB2 BANK.ACCOUNT (interest_accrued updated)          *
      *         DB2 BANK.TRANSACTION_HIST (INT postings on pay date) *
      *         DB2 BANK.DAILY_BALANCE (today's snapshot inserted)   *
      * CALLS:  INTRATE (Assembler) - rate computation engine        *
      * DB2 PLAN: INTPLAN                                             *
      * FREQUENCY: Daily (post day close)                            *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INTRPT ASSIGN TO INTRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  INTRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD                PIC X(133).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

       COPY WSCOMMON.
       COPY ERRORCD.

       01  WS-FATAL-ERROR-FLAG       PIC X(01) VALUE 'N'.
           88  FATAL-ERROR-FOUND     VALUE 'Y'.

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES
      *-----------------------------------------------------------------
       01  WS-HV.
           05  HV-ACCT-NUMBER       PIC X(12).
           05  HV-ACCT-TYPE         PIC X(03).
           05  HV-CURRENT-BALANCE   PIC S9(13)V99  COMP-3.
           05  HV-INTEREST-RATE     PIC S9(3)V9(6) COMP-3.
           05  HV-INTEREST-ACCRUED  PIC S9(13)V99  COMP-3.
           05  HV-INTEREST-YTD      PIC S9(13)V99  COMP-3.
           05  HV-INT-LAST-PAID     PIC X(10).
           05  HV-STMT-CYCLE        PIC X(02).
           05  HV-TRAN-ID           PIC X(16).
           05  HV-TRAN-AMOUNT       PIC S9(13)V99  COMP-3.
           05  HV-POST-DATE         PIC X(10).
           05  HV-OPEN-BAL          PIC S9(13)V99  COMP-3.
           05  HV-CLOSE-BAL         PIC S9(13)V99  COMP-3.
           05  HV-TOTAL-DR          PIC S9(13)V99  COMP-3.
           05  HV-TOTAL-CR          PIC S9(13)V99  COMP-3.
           05  HV-TRAN-COUNT        PIC S9(9)       COMP.
           05  HV-DAY-INTEREST      PIC S9(13)V99  COMP-3.

      *-----------------------------------------------------------------
      * DECLARE CURSORS
      *-----------------------------------------------------------------
           EXEC SQL
               DECLARE INT_CURSOR CURSOR FOR
               SELECT A.ACCT_NUMBER,
                      A.ACCT_TYPE,
                      A.CURRENT_BALANCE,
                      A.INTEREST_RATE,
                      A.INTEREST_ACCRUED,
                      A.INTEREST_YTD,
                      A.INTEREST_LAST_PAID_DT,
                      A.STMT_CYCLE
               FROM   BANK.ACCOUNT A
               WHERE  A.ACCT_STATUS = 'O'
               AND    A.ACCT_TYPE   IN ('SAV','MMA','CDA','IRA')
               AND    A.INTEREST_RATE > 0
               FOR    UPDATE OF INTEREST_ACCRUED,
                                INTEREST_YTD,
                                INTEREST_LAST_PAID_DT,
                                CURRENT_BALANCE,
                                LAST_UPDATE_TS,
                                LAST_UPDATE_USER
           END-EXEC.

      *-----------------------------------------------------------------
      * ASSEMBLER INTEREST RATE PARAMETERS
      *-----------------------------------------------------------------
       01  WS-INT-RATE-PARMS.
           05  IP-FUNC              PIC X(01).
           05  IP-ACCT-TYPE         PIC X(01).
           05  IP-BALANCE           PIC S9(13)V99 COMP-3.
           05  IP-ANNUAL-RATE       PIC S9(3)V9(6) COMP-3.
           05  IP-CALC-DAYS         PIC S9(4)     COMP-3.
           05  IP-INTEREST-AMT      PIC S9(13)V99 COMP-3.
           05  IP-RETURN-CODE       PIC X(02).

      *-----------------------------------------------------------------
      * INTEREST PAYMENT DETERMINATION
      *-----------------------------------------------------------------
       01  WS-PAYMENT-FLAG          PIC X(01) VALUE 'N'.
           88  WS-PAY-INTEREST      VALUE 'Y'.
           88  WS-ACCRUE-ONLY       VALUE 'N'.

       01  WS-STMT-DAY              PIC 9(02) COMP-3.
       01  WS-ASM-RC                PIC S9(4) COMP.
       01  WS-TRAN-SEED             PIC 9(16) COMP VALUE ZERO.

      *-----------------------------------------------------------------
      * REPORT LINES
      *-----------------------------------------------------------------
       01  WS-HDR1.
           05  FILLER PIC X(40)
               VALUE 'FIRST NATIONAL BANK - INTEREST ACCRUAL '.
           05  FILLER PIC X(40)
               VALUE 'REPORT                                  '.
           05  WS-HDR1-DATE PIC X(10).

       01  WS-HDR2.
           05  FILLER PIC X(12) VALUE 'ACCOUNT     '.
           05  FILLER PIC X(04) VALUE 'TYPE'.
           05  FILLER PIC X(17) VALUE '       BALANCE   '.
           05  FILLER PIC X(12) VALUE 'ANNUAL RATE '.
           05  FILLER PIC X(17) VALUE '   DAILY ACCRUAL '.
           05  FILLER PIC X(16) VALUE 'TOTAL ACCRUED   '.
           05  FILLER PIC X(08) VALUE 'PAID Y/N'.

       01  WS-DETAIL.
           05  WS-DET-ACCT          PIC X(12).
           05  FILLER               PIC X(01) VALUE SPACE.
           05  WS-DET-TYPE          PIC X(03).
           05  FILLER               PIC X(01) VALUE SPACE.
           05  WS-DET-BALANCE       PIC ZZZ,ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-RATE          PIC Z9.999999.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-DAILY         PIC ZZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-ACCRUED       PIC ZZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-PAID          PIC X(01).

      *-----------------------------------------------------------------
      * COUNTERS
      *-----------------------------------------------------------------
       01  WS-CNTS.
           05  WS-ACCTS-PROCESSED   PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-INT-ACCRUED-CNT   PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-INT-PAID-CNT      PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-INT-ERRORS        PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-TOTAL-ACCRUAL     PIC S9(15)V99 COMP-3 VALUE ZERO.
           05  WS-TOTAL-PAID        PIC S9(15)V99 COMP-3 VALUE ZERO.
           05  WS-COMMITS           PIC 9(05) COMP-3 VALUE ZERO.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS-ACCOUNTS
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'INTCALC: INTEREST CALCULATION STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE '-'
                  DELIMITED BY SIZE WS-CURRENT-MONTH
                  DELIMITED BY SIZE '-' DELIMITED BY SIZE
                  WS-CURRENT-DAY DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           OPEN OUTPUT INTRPT
           MOVE WS-BUSINESS-DATE TO WS-HDR1-DATE
           WRITE RPT-RECORD FROM WS-HDR1
           WRITE RPT-RECORD FROM WS-HDR2

           EXEC SQL OPEN INT_CURSOR END-EXEC
           IF SQLCODE NOT = 0
               DISPLAY 'INTCALC: ERROR OPENING INT_CURSOR SQLCODE='
                       SQLCODE
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.

       2000-PROCESS-ACCOUNTS.
           PERFORM 2100-FETCH-ACCOUNT
               UNTIL SQLCODE = +100 OR FATAL-ERROR-FOUND.

       2100-FETCH-ACCOUNT.
           EXEC SQL
               FETCH INT_CURSOR
               INTO  :HV-ACCT-NUMBER,
                     :HV-ACCT-TYPE,
                     :HV-CURRENT-BALANCE,
                     :HV-INTEREST-RATE,
                     :HV-INTEREST-ACCRUED,
                     :HV-INTEREST-YTD,
                     :HV-INT-LAST-PAID,
                     :HV-STMT-CYCLE
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   ADD 1 TO WS-ACCTS-PROCESSED
                   PERFORM 2200-CALCULATE-INTEREST THRU 2200-EXIT
               WHEN +100
                   CONTINUE
               WHEN OTHER
                   DISPLAY 'INTCALC: FETCH ERROR SQLCODE=' SQLCODE
                   SET FATAL-ERROR-FOUND TO TRUE
           END-EVALUATE.

       2200-CALCULATE-INTEREST.
      *    CALL ASSEMBLER ROUTINE FOR HIGH-PERFORMANCE CALC
           MOVE 'D'              TO IP-FUNC
           MOVE HV-ACCT-TYPE(1:1) TO IP-ACCT-TYPE
           MOVE HV-CURRENT-BALANCE TO IP-BALANCE
           MOVE HV-INTEREST-RATE   TO IP-ANNUAL-RATE
           MOVE 1                  TO IP-CALC-DAYS

           CALL 'INTRATE' USING WS-INT-RATE-PARMS
           MOVE RETURN-CODE TO WS-ASM-RC

           IF WS-ASM-RC NOT = ZERO
               DISPLAY 'INTCALC: INTRATE ERROR ACCT=' HV-ACCT-NUMBER
                       ' RC=' WS-ASM-RC
               ADD 1 TO WS-INT-ERRORS
               GO TO 2200-EXIT
           END-IF

           MOVE IP-INTEREST-AMT TO HV-DAY-INTEREST
           ADD HV-DAY-INTEREST TO HV-INTEREST-ACCRUED
           ADD HV-DAY-INTEREST TO HV-INTEREST-YTD
           ADD HV-DAY-INTEREST TO WS-TOTAL-ACCRUAL
           ADD 1 TO WS-INT-ACCRUED-CNT

      *    CHECK IF THIS IS INTEREST PAYMENT DATE (STMT CYCLE DAY)
           MOVE HV-STMT-CYCLE TO WS-STMT-DAY
           IF WS-CURRENT-DAY = WS-STMT-DAY
               MOVE 'Y' TO WS-PAYMENT-FLAG
           ELSE
               MOVE 'N' TO WS-PAYMENT-FLAG
           END-IF

      *    POST INTEREST PAYMENT IF DUE
           IF WS-PAY-INTEREST
               PERFORM 2300-POST-INTEREST-PAYMENT
           END-IF

      *    UPDATE ACCOUNT RECORD
           EXEC SQL
               UPDATE BANK.ACCOUNT
               SET    INTEREST_ACCRUED     = :HV-INTEREST-ACCRUED,
                      INTEREST_YTD         = :HV-INTEREST-YTD,
                      LAST_UPDATE_TS       = CURRENT TIMESTAMP,
                      LAST_UPDATE_USER     = 'INTCALC'
               WHERE  CURRENT OF INT_CURSOR
           END-EXEC

           IF SQLCODE NOT = 0
               DISPLAY 'INTCALC: UPDATE ERROR ACCT='
                       HV-ACCT-NUMBER ' SQLCODE=' SQLCODE
               ADD 1 TO WS-INT-ERRORS
               EXEC SQL ROLLBACK END-EXEC
               GO TO 2200-EXIT
           END-IF

      *    INSERT DAILY BALANCE SNAPSHOT
           MOVE WS-BUSINESS-DATE   TO HV-POST-DATE
           MOVE HV-CURRENT-BALANCE TO HV-OPEN-BAL
           MOVE HV-CURRENT-BALANCE TO HV-CLOSE-BAL
           MOVE HV-DAY-INTEREST    TO HV-DAY-INTEREST

           EXEC SQL
               INSERT INTO BANK.DAILY_BALANCE
                      (ACCT_NUMBER, BALANCE_DATE, OPENING_BALANCE,
                       CLOSING_BALANCE, INTEREST_ACCRUED)
               VALUES (:HV-ACCT-NUMBER, :HV-POST-DATE,
                       :HV-OPEN-BAL, :HV-CLOSE-BAL, :HV-DAY-INTEREST)
           END-EXEC

           ADD 1 TO WS-COMMIT-COUNT
           IF WS-COMMIT-COUNT >= WS-COMMIT-FREQ
               EXEC SQL COMMIT END-EXEC
               ADD 1 TO WS-COMMITS
               MOVE ZERO TO WS-COMMIT-COUNT
           END-IF

      *    WRITE REPORT LINE
           MOVE HV-ACCT-NUMBER     TO WS-DET-ACCT
           MOVE HV-ACCT-TYPE       TO WS-DET-TYPE
           MOVE HV-CURRENT-BALANCE TO WS-DET-BALANCE
           MOVE HV-INTEREST-RATE   TO WS-DET-RATE
           MOVE HV-DAY-INTEREST    TO WS-DET-DAILY
           MOVE HV-INTEREST-ACCRUED TO WS-DET-ACCRUED
           MOVE WS-PAYMENT-FLAG    TO WS-DET-PAID
           WRITE RPT-RECORD FROM WS-DETAIL.

       2200-EXIT.
           CONTINUE.

       2300-POST-INTEREST-PAYMENT.
           ADD 1 TO WS-TRAN-SEED
           MOVE WS-TRAN-SEED TO HV-TRAN-ID
           MOVE HV-INTEREST-ACCRUED TO HV-TRAN-AMOUNT
           ADD HV-INTEREST-ACCRUED TO HV-CURRENT-BALANCE
           ADD HV-INTEREST-ACCRUED TO WS-TOTAL-PAID
           MOVE ZERO TO HV-INTEREST-ACCRUED
           MOVE WS-BUSINESS-DATE TO HV-INT-LAST-PAID

           EXEC SQL
               INSERT INTO BANK.TRANSACTION_HIST
                      (TRAN_ID, ACCT_NUMBER, TRAN_TYPE, TRAN_CODE,
                       AMOUNT, EFFECTIVE_DATE, POST_DATE,
                       DESCRIPTION, CHANNEL, TRAN_STATUS)
               VALUES (:HV-TRAN-ID, :HV-ACCT-NUMBER, 'CR', 'INT ',
                       :HV-TRAN-AMOUNT, :WS-BUSINESS-DATE,
                       :WS-BUSINESS-DATE,
                       'INTEREST PAYMENT', 'BAT', 'P')
           END-EXEC

           IF SQLCODE = 0
               ADD 1 TO WS-INT-PAID-CNT
               EXEC SQL
                   UPDATE BANK.ACCOUNT
                   SET    CURRENT_BALANCE       = :HV-CURRENT-BALANCE,
                          AVAILABLE_BALANCE     = :HV-CURRENT-BALANCE,
                          INTEREST_ACCRUED      = 0,
                          INTEREST_LAST_PAID_DT = :HV-INT-LAST-PAID,
                          LAST_UPDATE_TS        = CURRENT TIMESTAMP,
                          LAST_UPDATE_USER      = 'INTCALC'
                   WHERE  CURRENT OF INT_CURSOR
               END-EXEC
           ELSE
               DISPLAY 'INTCALC: ERROR POSTING INTEREST TRAN ACCT='
                       HV-ACCT-NUMBER ' SQLCODE=' SQLCODE
               ADD 1 TO WS-INT-ERRORS
           END-IF.

       3000-FINALIZE.
           EXEC SQL COMMIT END-EXEC
           EXEC SQL CLOSE INT_CURSOR END-EXEC

           CLOSE INTRPT

           DISPLAY 'INTCALC: INTEREST CALCULATION COMPLETE'
           DISPLAY 'ACCOUNTS PROCESSED:  ' WS-ACCTS-PROCESSED
           DISPLAY 'ACCRUALS POSTED:     ' WS-INT-ACCRUED-CNT
           DISPLAY 'INTEREST PAID:       ' WS-INT-PAID-CNT
           DISPLAY 'TOTAL ACCRUAL:       ' WS-TOTAL-ACCRUAL
           DISPLAY 'TOTAL PAID:          ' WS-TOTAL-PAID
           DISPLAY 'ERRORS:              ' WS-INT-ERRORS

           IF WS-INT-ERRORS > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
