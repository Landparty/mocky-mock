       IDENTIFICATION DIVISION.
       PROGRAM-ID. STMTGEN.
      *****************************************************************
      * STATEMENT GENERATION BATCH PROGRAM                           *
      * DESCRIPTION: Generates monthly account statements for all    *
      *   accounts whose statement cycle date matches today. Output  *
      *   is written to a GDG dataset for print/electronic delivery. *
      * INPUT:  DB2 BANK.ACCOUNT         (account master)            *
      *         DB2 BANK.CUSTOMER        (customer name/address)     *
      *         DB2 BANK.TRANSACTION_HIST (period transactions)      *
      * OUTPUT: STMTOUT  - GDG statement output file                 *
      *         STMTRPT  - Run statistics report                      *
      *         DB2 BANK.ACCOUNT (last_stmt_date updated)            *
      * CALLS:  STMTFMT (PL/I) - statement line formatting           *
      *         CURRFMT (Assembler) - currency formatting             *
      * DB2 PLAN: STMTPLAN                                           *
      * FREQUENCY: Daily (processes accounts by cycle date)          *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT STMTOUT ASSIGN TO STMTOUT
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-STMT-STATUS.

           SELECT STMTRPT ASSIGN TO STMTRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  STMTOUT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  STMT-OUTPUT-RECORD        PIC X(133).

       FD  STMTRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD                PIC X(133).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

       COPY WSCOMMON.
       COPY ERRORCD.
       COPY STMTREC.

       01  WS-STMT-STATUS            PIC X(02).
           88  WS-STMT-OK            VALUE '00'.

       01  WS-FATAL-ERROR-FLAG       PIC X(01) VALUE 'N'.
           88  FATAL-ERROR-FOUND     VALUE 'Y'.

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES
      *-----------------------------------------------------------------
       01  WS-STMT-HV.
           05  HV-ACCT-NUMBER        PIC X(12).
           05  HV-ACCT-TYPE          PIC X(03).
           05  HV-CIF-NUMBER         PIC X(10).
           05  HV-LAST-STMT-DATE     PIC X(10).
           05  HV-STMT-CYCLE         PIC X(02).
           05  HV-CURRENT-BALANCE    PIC S9(13)V99 COMP-3.
           05  HV-FIRST-NAME         PIC X(25).
           05  HV-LAST-NAME          PIC X(30).
           05  HV-ADDR1              PIC X(40).
           05  HV-ADDR2              PIC X(40).
           05  HV-CITY               PIC X(25).
           05  HV-STATE              PIC X(02).
           05  HV-ZIP                PIC X(10).
           05  HV-TRAN-ID            PIC X(16).
           05  HV-TRAN-TYPE          PIC X(02).
           05  HV-TRAN-CODE          PIC X(04).
           05  HV-TRAN-AMOUNT        PIC S9(13)V99 COMP-3.
           05  HV-TRAN-DATE          PIC X(10).
           05  HV-POST-DATE          PIC X(10).
           05  HV-TRAN-DESC          PIC X(40).
           05  HV-CHECK-NUM          PIC X(10).
           05  HV-RUN-BAL            PIC S9(13)V99 COMP-3.

      *-----------------------------------------------------------------
      * ACCOUNT STATEMENT CURSOR
      *-----------------------------------------------------------------
           EXEC SQL
               DECLARE STMT_ACCT_CUR CURSOR FOR
               SELECT A.ACCT_NUMBER,
                      A.ACCT_TYPE,
                      A.CIF_NUMBER,
                      A.LAST_STMT_DATE,
                      A.STMT_CYCLE,
                      A.CURRENT_BALANCE
               FROM   BANK.ACCOUNT A
               WHERE  A.ACCT_STATUS = 'O'
               AND    A.STMT_CYCLE   = :HV-STMT-CYCLE
               FOR    UPDATE OF LAST_STMT_DATE,
                                LAST_UPDATE_TS,
                                LAST_UPDATE_USER
           END-EXEC.

      *-----------------------------------------------------------------
      * TRANSACTION CURSOR (PER ACCOUNT)
      *-----------------------------------------------------------------
           EXEC SQL
               DECLARE STMT_TRAN_CUR CURSOR FOR
               SELECT T.TRAN_ID,
                      T.TRAN_TYPE,
                      T.TRAN_CODE,
                      T.AMOUNT,
                      T.EFFECTIVE_DATE,
                      T.POST_DATE,
                      T.DESCRIPTION,
                      T.CHECK_NUMBER,
                      T.RUNNING_BALANCE
               FROM   BANK.TRANSACTION_HIST T
               WHERE  T.ACCT_NUMBER = :HV-ACCT-NUMBER
               AND    T.POST_DATE   > :HV-LAST-STMT-DATE
               AND    T.POST_DATE   <= :HV-POST-DATE
               AND    T.TRAN_STATUS = 'P'
               ORDER BY T.POST_DATE ASC, T.TRAN_TIMESTAMP ASC
           END-EXEC.

      *-----------------------------------------------------------------
      * STATEMENT FORMATTER PARMS (CALL TO PL/I STMTFMT)
      *-----------------------------------------------------------------
       01  WS-STMT-FMT-PARMS.
           05  SF-FUNCTION           PIC X(01).
           05  SF-ACCT-NUM           PIC X(12).
           05  SF-CUST-NAME          PIC X(56).
           05  SF-STMT-DATE          PIC X(10).
           05  SF-PERIOD-BEGIN       PIC X(10).
           05  SF-PERIOD-END         PIC X(10).
           05  SF-OPEN-BAL           PIC S9(13)V99 COMP-3.
           05  SF-CLOSE-BAL          PIC S9(13)V99 COMP-3.
           05  SF-TRAN-DATE          PIC X(10).
           05  SF-TRAN-DESC          PIC X(40).
           05  SF-TRAN-REF           PIC X(20).
           05  SF-TRAN-CODE          PIC X(04).
           05  SF-DEBIT-AMT          PIC S9(13)V99 COMP-3.
           05  SF-CREDIT-AMT         PIC S9(13)V99 COMP-3.
           05  SF-RUN-BAL            PIC S9(13)V99 COMP-3.
           05  SF-CHECK-NUM          PIC X(10).
           05  SF-LINE-NUM           PIC S9(4) COMP.
           05  SF-PAGE-NUM           PIC S9(4) COMP.
           05  SF-OUTPUT-LINE        PIC X(133).
           05  SF-RETURN-CODE        PIC S9(4) COMP.

      *-----------------------------------------------------------------
      * STATEMENT ACCUMULATORS
      *-----------------------------------------------------------------
       01  WS-STMT-ACCUM.
           05  WS-STMT-OPEN-BAL     PIC S9(13)V99 COMP-3 VALUE ZERO.
           05  WS-STMT-CLOSE-BAL    PIC S9(13)V99 COMP-3 VALUE ZERO.
           05  WS-STMT-TOTAL-DR     PIC S9(13)V99 COMP-3 VALUE ZERO.
           05  WS-STMT-TOTAL-CR     PIC S9(13)V99 COMP-3 VALUE ZERO.
           05  WS-STMT-LINE-CNT     PIC 9(04) COMP-3 VALUE ZERO.
           05  WS-STMT-PAGE-CNT     PIC 9(03) COMP-3 VALUE 1.
           05  WS-STMT-TRAN-CNT     PIC 9(05) COMP-3 VALUE ZERO.

       01  WS-CYCLE-DAY              PIC X(02).
       01  WS-PLIRETC                PIC S9(4) COMP.
       01  WS-STMT-PERIOD-BEGIN      PIC X(10).

      *-----------------------------------------------------------------
      * COUNTERS
      *-----------------------------------------------------------------
       01  WS-STMT-CNTS.
           05  WS-STMTS-GENERATED   PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-TRAN-LINES        PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-STMT-ERRORS       PIC 9(05) COMP-3 VALUE ZERO.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS-STATEMENTS
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'STMTGEN: STATEMENT GENERATION STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE '-'
                  DELIMITED BY SIZE WS-CURRENT-MONTH
                  DELIMITED BY SIZE '-' DELIMITED BY SIZE
                  WS-CURRENT-DAY DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           MOVE WS-CURRENT-DAY TO WS-CYCLE-DAY
           MOVE WS-CYCLE-DAY   TO HV-STMT-CYCLE

           OPEN OUTPUT STMTOUT
           OPEN OUTPUT STMTRPT

           EXEC SQL OPEN STMT_ACCT_CUR END-EXEC
           IF SQLCODE NOT = 0
               DISPLAY 'STMTGEN: CANNOT OPEN STMT_ACCT_CUR SQLCODE='
                       SQLCODE
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.

       2000-PROCESS-STATEMENTS.
           PERFORM 2100-FETCH-ACCOUNT
               UNTIL SQLCODE = +100 OR FATAL-ERROR-FOUND.

       2100-FETCH-ACCOUNT.
           EXEC SQL
               FETCH STMT_ACCT_CUR
               INTO  :HV-ACCT-NUMBER,
                     :HV-ACCT-TYPE,
                     :HV-CIF-NUMBER,
                     :HV-LAST-STMT-DATE,
                     :HV-STMT-CYCLE,
                     :HV-CURRENT-BALANCE
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   PERFORM 2200-FETCH-CUSTOMER-INFO
                   PERFORM 2300-GENERATE-STATEMENT
                   PERFORM 2600-UPDATE-STMT-DATE
               WHEN +100
                   CONTINUE
               WHEN OTHER
                   DISPLAY 'STMTGEN: FETCH ERROR SQLCODE=' SQLCODE
                   SET FATAL-ERROR-FOUND TO TRUE
           END-EVALUATE.

       2200-FETCH-CUSTOMER-INFO.
           EXEC SQL
               SELECT C.FIRST_NAME, C.LAST_NAME,
                      C.ADDR_LINE1,  C.ADDR_LINE2,
                      C.CITY, C.STATE, C.ZIP
               INTO   :HV-FIRST-NAME, :HV-LAST-NAME,
                      :HV-ADDR1, :HV-ADDR2,
                      :HV-CITY, :HV-STATE, :HV-ZIP
               FROM   BANK.CUSTOMER C
               WHERE  C.CIF_NUMBER = :HV-CIF-NUMBER
           END-EXEC
           IF SQLCODE NOT = 0
               MOVE SPACES TO HV-FIRST-NAME HV-LAST-NAME
           END-IF.

       2300-GENERATE-STATEMENT.
           INITIALIZE WS-STMT-ACCUM

           STRING HV-FIRST-NAME DELIMITED BY SPACE
                  ' ' DELIMITED BY SIZE
                  HV-LAST-NAME  DELIMITED BY SPACE
                  INTO SF-CUST-NAME
           END-STRING

           MOVE HV-ACCT-NUMBER    TO SF-ACCT-NUM
           MOVE WS-BUSINESS-DATE  TO SF-STMT-DATE
           MOVE HV-LAST-STMT-DATE TO WS-STMT-PERIOD-BEGIN
           MOVE HV-LAST-STMT-DATE TO SF-PERIOD-BEGIN
           MOVE WS-BUSINESS-DATE  TO SF-PERIOD-END
           MOVE 1                 TO SF-PAGE-NUM

      *    FORMAT AND WRITE HEADER
           MOVE 'H' TO SF-FUNCTION
           CALL 'STMTFMT' USING WS-STMT-FMT-PARMS
           WRITE STMT-OUTPUT-RECORD FROM SF-OUTPUT-LINE

      *    OPEN TRANSACTION CURSOR AND WRITE DETAIL LINES
           MOVE HV-ACCT-NUMBER TO HV-ACCT-NUMBER
           MOVE WS-BUSINESS-DATE TO HV-POST-DATE
           EXEC SQL OPEN STMT_TRAN_CUR END-EXEC

           PERFORM 2400-FETCH-TRANSACTIONS
               UNTIL SQLCODE = +100

           EXEC SQL CLOSE STMT_TRAN_CUR END-EXEC

      *    FORMAT SUMMARY LINE
           MOVE 'S' TO SF-FUNCTION
           MOVE HV-CURRENT-BALANCE TO SF-CLOSE-BAL
           CALL 'STMTFMT' USING WS-STMT-FMT-PARMS
           WRITE STMT-OUTPUT-RECORD FROM SF-OUTPUT-LINE

           ADD 1 TO WS-STMTS-GENERATED.

       2400-FETCH-TRANSACTIONS.
           EXEC SQL
               FETCH STMT_TRAN_CUR
               INTO  :HV-TRAN-ID, :HV-TRAN-TYPE, :HV-TRAN-CODE,
                     :HV-TRAN-AMOUNT, :HV-TRAN-DATE, :HV-POST-DATE,
                     :HV-TRAN-DESC, :HV-CHECK-NUM, :HV-RUN-BAL
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   ADD 1 TO WS-STMT-LINE-CNT
                   ADD 1 TO WS-TRAN-LINES

                   IF WS-STMT-LINE-CNT > 50
                       MOVE 'P' TO SF-FUNCTION
                       ADD 1 TO WS-STMT-PAGE-CNT
                       MOVE WS-STMT-PAGE-CNT TO SF-PAGE-NUM
                       CALL 'STMTFMT' USING WS-STMT-FMT-PARMS
                       WRITE STMT-OUTPUT-RECORD FROM SF-OUTPUT-LINE
                       MOVE ZERO TO WS-STMT-LINE-CNT
                   END-IF

                   MOVE 'D'           TO SF-FUNCTION
                   MOVE HV-POST-DATE  TO SF-TRAN-DATE
                   MOVE HV-TRAN-DESC  TO SF-TRAN-DESC
                   MOVE HV-TRAN-CODE  TO SF-TRAN-CODE
                   MOVE HV-CHECK-NUM  TO SF-CHECK-NUM
                   MOVE HV-RUN-BAL    TO SF-RUN-BAL

                   IF HV-TRAN-TYPE = 'DR'
                       MOVE HV-TRAN-AMOUNT TO SF-DEBIT-AMT
                       MOVE ZERO           TO SF-CREDIT-AMT
                   ELSE
                       MOVE HV-TRAN-AMOUNT TO SF-CREDIT-AMT
                       MOVE ZERO           TO SF-DEBIT-AMT
                   END-IF

                   CALL 'STMTFMT' USING WS-STMT-FMT-PARMS
                   WRITE STMT-OUTPUT-RECORD FROM SF-OUTPUT-LINE
               WHEN +100
                   CONTINUE
               WHEN OTHER
                   DISPLAY 'STMTGEN: TRAN FETCH ERROR SQLCODE=' SQLCODE
                   ADD 1 TO WS-STMT-ERRORS
           END-EVALUATE.

       2600-UPDATE-STMT-DATE.
           EXEC SQL
               UPDATE BANK.ACCOUNT
               SET    LAST_STMT_DATE   = :WS-BUSINESS-DATE,
                      LAST_UPDATE_TS   = CURRENT TIMESTAMP,
                      LAST_UPDATE_USER = 'STMTGEN'
               WHERE  CURRENT OF STMT_ACCT_CUR
           END-EXEC

           IF SQLCODE = 0
               ADD 1 TO WS-COMMIT-COUNT
               IF WS-COMMIT-COUNT >= WS-COMMIT-FREQ
                   EXEC SQL COMMIT END-EXEC
                   MOVE ZERO TO WS-COMMIT-COUNT
               END-IF
           END-IF.

       3000-FINALIZE.
           EXEC SQL COMMIT END-EXEC
           EXEC SQL CLOSE STMT_ACCT_CUR END-EXEC

           CLOSE STMTOUT
           CLOSE STMTRPT

           DISPLAY 'STMTGEN: STATEMENT GENERATION COMPLETE'
           DISPLAY 'STATEMENTS GENERATED: ' WS-STMTS-GENERATED
           DISPLAY 'TRANSACTION LINES:    ' WS-TRAN-LINES
           DISPLAY 'ERRORS:               ' WS-STMT-ERRORS

           IF WS-STMT-ERRORS > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
