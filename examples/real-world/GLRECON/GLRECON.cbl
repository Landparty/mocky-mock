       IDENTIFICATION DIVISION.
       PROGRAM-ID. GLRECON.
      *****************************************************************
      * GENERAL LEDGER RECONCILIATION PROGRAM                        *
      * DESCRIPTION: End-of-day GL reconciliation. Aggregates all    *
      *   transaction postings into GL debit/credit totals, updates   *
      *   GL account balances, and produces out-of-balance report.   *
      * INPUT:  DB2 BANK.TRANSACTION_HIST (today's posted trans)     *
      *         DB2 BANK.GL_ACCOUNT        (GL master)               *
      *         GLMAP - SYSIN GL mapping control cards               *
      * OUTPUT: DB2 BANK.GL_ACCOUNT (balances updated)               *
      *         GLRPT   - GL reconciliation report                    *
      *         GLEXCPT - Out-of-balance exception report             *
      * DB2 PLAN: GLPLAN                                              *
      * FREQUENCY: Daily (last step in EOD cycle)                    *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT GLRPT   ASSIGN TO GLRPT
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT GLEXCPT ASSIGN TO GLEXCPT
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT GLMAP   ASSIGN TO GLMAPDD
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  GLRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  GLRPT-RECORD              PIC X(133).

       FD  GLEXCPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  GLEXCPT-RECORD            PIC X(133).

       FD  GLMAP
           RECORDING MODE IS V.
       01  GLMAP-RECORD              PIC X(80).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

       COPY WSCOMMON.
       COPY ERRORCD.
       COPY GLACCT.

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES
      *-----------------------------------------------------------------
       01  WS-GL-HV.
           05  HV-GL-ACCT            PIC X(10).
           05  HV-GL-TYPE            PIC X(01).
           05  HV-TRAN-CODE          PIC X(04).
           05  HV-TOTAL-DEBITS       PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-CREDITS      PIC S9(17)V99 COMP-3.
           05  HV-NET-CHANGE         PIC S9(17)V99 COMP-3.
           05  HV-CURRENT-DEBIT-BAL  PIC S9(17)V99 COMP-3.
           05  HV-CURRENT-CREDIT-BAL PIC S9(17)V99 COMP-3.
           05  HV-CURRENT-NET-BAL    PIC S9(17)V99 COMP-3.
           05  HV-PRIOR-DAY-BAL      PIC S9(17)V99 COMP-3.
           05  HV-MTD-DR             PIC S9(17)V99 COMP-3.
           05  HV-MTD-CR             PIC S9(17)V99 COMP-3.
           05  HV-POST-DATE          PIC X(10).
           05  HV-TRAN-COUNT         PIC S9(9)      COMP.

      *-----------------------------------------------------------------
      * GL MAPPING CONTROL CARD STRUCTURE
      *-----------------------------------------------------------------
       01  WS-GLMAP-RECORD.
           05  WS-MAP-TRAN-CODE      PIC X(04).
           05  FILLER                PIC X(01).
           05  WS-MAP-DR-GL-ACCT     PIC X(10).
           05  FILLER                PIC X(01).
           05  WS-MAP-CR-GL-ACCT     PIC X(10).
           05  FILLER                PIC X(54).

       01  WS-MAP-EOF               PIC X(01) VALUE 'N'.
           88  WS-MAP-AT-EOF        VALUE 'Y'.

      *-----------------------------------------------------------------
      * GL AGGREGATION CURSOR - SUMS TRANS BY TRAN CODE FOR TODAY
      *-----------------------------------------------------------------
           EXEC SQL
               DECLARE GL_AGG_CUR CURSOR FOR
               SELECT   TRAN_CODE,
                        TRAN_TYPE,
                        SUM(AMOUNT)  AS TOT_AMT,
                        COUNT(*)     AS TRAN_CNT
               FROM     BANK.TRANSACTION_HIST
               WHERE    POST_DATE    = :HV-POST-DATE
               AND      TRAN_STATUS  = 'P'
               GROUP BY TRAN_CODE, TRAN_TYPE
               ORDER BY TRAN_CODE, TRAN_TYPE
           END-EXEC.

      *-----------------------------------------------------------------
      * GL BALANCE CURSOR
      *-----------------------------------------------------------------
           EXEC SQL
               DECLARE GL_BAL_CUR CURSOR FOR
               SELECT GL_ACCT_NUMBER,
                      GL_ACCT_TYPE,
                      DEBIT_BALANCE,
                      CREDIT_BALANCE,
                      NET_BALANCE,
                      MTD_DEBITS,
                      MTD_CREDITS
               FROM   BANK.GL_ACCOUNT
               WHERE  GL_STATUS = 'A'
               FOR    UPDATE OF DEBIT_BALANCE,
                                CREDIT_BALANCE,
                                NET_BALANCE,
                                PRIOR_DAY_BALANCE,
                                MTD_DEBITS,
                                MTD_CREDITS,
                                LAST_POST_DATE,
                                LAST_UPDATE_TS,
                                LAST_UPDATE_USER
           END-EXEC.

      *-----------------------------------------------------------------
      * OUT-OF-BALANCE TRACKING
      *-----------------------------------------------------------------
       01  WS-BALANCE-CHECK.
           05  WS-TOTAL-ALL-DEBITS   PIC S9(17)V99 COMP-3 VALUE ZERO.
           05  WS-TOTAL-ALL-CREDITS  PIC S9(17)V99 COMP-3 VALUE ZERO.
           05  WS-BALANCE-DIFF       PIC S9(17)V99 COMP-3 VALUE ZERO.
           05  WS-OUT-OF-BALANCE     PIC X(01) VALUE 'N'.
               88  WS-IS-OUT-OF-BAL  VALUE 'Y'.
               88  WS-IS-IN-BALANCE  VALUE 'N'.

      *-----------------------------------------------------------------
      * REPORT LINE AREAS
      *-----------------------------------------------------------------
       01  WS-GL-HDR.
           05  FILLER PIC X(30)
               VALUE 'FIRST NATIONAL BANK - GL RECON'.
           05  FILLER PIC X(15) VALUE ' REPORT - DATE:'.
           05  WS-HDR-DATE PIC X(10).
           05  FILLER PIC X(78) VALUE SPACES.

       01  WS-GL-COL-HDR.
           05  FILLER PIC X(11) VALUE 'GL ACCOUNT '.
           05  FILLER PIC X(12) VALUE 'TYPE   NAME'.
           05  FILLER PIC X(20) VALUE '         DEBITS     '.
           05  FILLER PIC X(20) VALUE '        CREDITS     '.
           05  FILLER PIC X(20) VALUE '        NET BAL     '.
           05  FILLER PIC X(10) VALUE 'STATUS    '.

       01  WS-GL-DETAIL.
           05  WS-GLD-ACCT          PIC X(10).
           05  FILLER               PIC X(01) VALUE SPACE.
           05  WS-GLD-TYPE          PIC X(01).
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-GLD-DEBITS        PIC ZZ,ZZZ,ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-GLD-CREDITS       PIC ZZ,ZZZ,ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-GLD-NET           PIC ZZ,ZZZ,ZZZ,ZZZ,ZZ9.99-.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-GLD-STATUS        PIC X(10).

      *-----------------------------------------------------------------
      * COUNTERS
      *-----------------------------------------------------------------
       01  WS-GL-CNTS.
           05  WS-GL-ACCTS-PROC     PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-GL-ACCTS-OOB      PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-TRAN-TYPES-PROC   PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-GL-ERRORS         PIC 9(05) COMP-3 VALUE ZERO.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-AGGREGATE-TRANSACTIONS
           PERFORM 3000-UPDATE-GL-BALANCES
           PERFORM 4000-VERIFY-BALANCE
           PERFORM 5000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'GLRECON: GL RECONCILIATION STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE '-'
                  DELIMITED BY SIZE WS-CURRENT-MONTH
                  DELIMITED BY SIZE '-' DELIMITED BY SIZE
                  WS-CURRENT-DAY DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           MOVE WS-BUSINESS-DATE TO HV-POST-DATE
           MOVE WS-BUSINESS-DATE TO WS-HDR-DATE

           OPEN OUTPUT GLRPT
           OPEN OUTPUT GLEXCPT
           OPEN INPUT  GLMAP

           WRITE GLRPT-RECORD FROM WS-GL-HDR
           WRITE GLRPT-RECORD FROM WS-GL-COL-HDR.

       2000-AGGREGATE-TRANSACTIONS.
           DISPLAY 'GLRECON: AGGREGATING TRANSACTION POSTINGS'

           EXEC SQL OPEN GL_AGG_CUR END-EXEC
           IF SQLCODE NOT = 0
               DISPLAY 'GLRECON: ERROR OPENING GL_AGG_CUR SQLCODE='
                       SQLCODE
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF

           PERFORM 2100-FETCH-AGGREGATE
               UNTIL SQLCODE = +100

           EXEC SQL CLOSE GL_AGG_CUR END-EXEC.

       2100-FETCH-AGGREGATE.
           EXEC SQL
               FETCH GL_AGG_CUR
               INTO  :HV-TRAN-CODE,
                     :HV-GL-TYPE,
                     :HV-TOTAL-DEBITS,
                     :HV-TRAN-COUNT
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   ADD 1 TO WS-TRAN-TYPES-PROC
                   DISPLAY 'GLRECON: TRAN CODE=' HV-TRAN-CODE
                           ' TYPE=' HV-GL-TYPE
                           ' AMOUNT=' HV-TOTAL-DEBITS
                           ' COUNT=' HV-TRAN-COUNT
               WHEN +100
                   CONTINUE
               WHEN OTHER
                   DISPLAY 'GLRECON: AGGREGATE FETCH ERROR SQLCODE='
                           SQLCODE
                   ADD 1 TO WS-GL-ERRORS
           END-EVALUATE.

       3000-UPDATE-GL-BALANCES.
           DISPLAY 'GLRECON: UPDATING GL ACCOUNT BALANCES'

           EXEC SQL OPEN GL_BAL_CUR END-EXEC

           PERFORM 3100-FETCH-GL-ACCOUNT
               UNTIL SQLCODE = +100

           EXEC SQL CLOSE GL_BAL_CUR END-EXEC.

       3100-FETCH-GL-ACCOUNT.
           EXEC SQL
               FETCH GL_BAL_CUR
               INTO  :HV-GL-ACCT,
                     :HV-GL-TYPE,
                     :HV-CURRENT-DEBIT-BAL,
                     :HV-CURRENT-CREDIT-BAL,
                     :HV-CURRENT-NET-BAL,
                     :HV-MTD-DR,
                     :HV-MTD-CR
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   ADD 1 TO WS-GL-ACCTS-PROC
                   COMPUTE HV-NET-CHANGE = HV-TOTAL-DEBITS -
                           HV-TOTAL-CREDITS
                   ADD HV-TOTAL-DEBITS  TO HV-CURRENT-DEBIT-BAL
                   ADD HV-TOTAL-CREDITS TO HV-CURRENT-CREDIT-BAL
                   COMPUTE HV-CURRENT-NET-BAL = HV-CURRENT-DEBIT-BAL -
                           HV-CURRENT-CREDIT-BAL
                   ADD HV-TOTAL-DEBITS  TO HV-MTD-DR
                   ADD HV-TOTAL-CREDITS TO HV-MTD-CR

                   EXEC SQL
                       UPDATE BANK.GL_ACCOUNT
                       SET    DEBIT_BALANCE    = :HV-CURRENT-DEBIT-BAL,
                              CREDIT_BALANCE   = :HV-CURRENT-CREDIT-BAL,
                              NET_BALANCE      = :HV-CURRENT-NET-BAL,
                              PRIOR_DAY_BALANCE = :HV-PRIOR-DAY-BAL,
                              MTD_DEBITS       = :HV-MTD-DR,
                              MTD_CREDITS      = :HV-MTD-CR,
                              LAST_POST_DATE   = :HV-POST-DATE,
                              LAST_UPDATE_TS   = CURRENT TIMESTAMP,
                              LAST_UPDATE_USER = 'GLRECON'
                       WHERE  CURRENT OF GL_BAL_CUR
                   END-EXEC

                   MOVE HV-GL-ACCT          TO WS-GLD-ACCT
                   MOVE HV-GL-TYPE          TO WS-GLD-TYPE
                   MOVE HV-CURRENT-DEBIT-BAL TO WS-GLD-DEBITS
                   MOVE HV-CURRENT-CREDIT-BAL TO WS-GLD-CREDITS
                   MOVE HV-CURRENT-NET-BAL  TO WS-GLD-NET

                   ADD HV-CURRENT-DEBIT-BAL  TO WS-TOTAL-ALL-DEBITS
                   ADD HV-CURRENT-CREDIT-BAL TO WS-TOTAL-ALL-CREDITS
                   WRITE GLRPT-RECORD FROM WS-GL-DETAIL
               WHEN +100
                   CONTINUE
               WHEN OTHER
                   DISPLAY 'GLRECON: GL FETCH ERROR SQLCODE=' SQLCODE
                   ADD 1 TO WS-GL-ERRORS
           END-EVALUATE.

       4000-VERIFY-BALANCE.
           COMPUTE WS-BALANCE-DIFF = WS-TOTAL-ALL-DEBITS -
                   WS-TOTAL-ALL-CREDITS
           IF WS-BALANCE-DIFF NOT = ZERO
               SET WS-IS-OUT-OF-BAL TO TRUE
               ADD 1 TO WS-GL-ERRORS
               DISPLAY 'GLRECON: *** OUT OF BALANCE ***'
               DISPLAY 'GLRECON: TOTAL DEBITS =' WS-TOTAL-ALL-DEBITS
               DISPLAY 'GLRECON: TOTAL CREDITS=' WS-TOTAL-ALL-CREDITS
               DISPLAY 'GLRECON: DIFFERENCE   =' WS-BALANCE-DIFF
               WRITE GLEXCPT-RECORD FROM
                   'GENERAL LEDGER OUT OF BALANCE - REQUIRES '
               WRITE GLEXCPT-RECORD FROM
                   'IMMEDIATE INVESTIGATION BY ACCOUNTING DEPT'
           ELSE
               DISPLAY 'GLRECON: GL IS IN BALANCE'
           END-IF.

       5000-FINALIZE.
           EXEC SQL COMMIT END-EXEC

           CLOSE GLRPT
           CLOSE GLEXCPT
           CLOSE GLMAP

           DISPLAY 'GLRECON: RECONCILIATION COMPLETE'
           DISPLAY 'GL ACCOUNTS PROCESSED: ' WS-GL-ACCTS-PROC
           DISPLAY 'TRAN TYPES PROCESSED:  ' WS-TRAN-TYPES-PROC
           DISPLAY 'GL ERRORS:             ' WS-GL-ERRORS
           DISPLAY 'TOTAL DEBITS:          ' WS-TOTAL-ALL-DEBITS
           DISPLAY 'TOTAL CREDITS:         ' WS-TOTAL-ALL-CREDITS

           IF WS-IS-OUT-OF-BAL
               MOVE 8 TO RETURN-CODE
           ELSE IF WS-GL-ERRORS > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
