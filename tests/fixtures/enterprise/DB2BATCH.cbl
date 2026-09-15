       IDENTIFICATION DIVISION.
       PROGRAM-ID. DB2BATCH.
      *================================================================*
      * Program type: DB2 batch program (TSO/IKJEFT01 or DSN RUN).     *
      * SQLCA, DCLGEN-style DECLARE TABLE with host structure and null *
      * indicators, a WITH HOLD cursor, positioned UPDATE, multi-row   *
      * FETCH into host arrays, WHENEVER, commit frequency, DSNTIAR.   *
      *================================================================*
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PARM-FILE ASSIGN TO PARMIN
               FILE STATUS IS WS-PARM-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  PARM-FILE
           RECORDING MODE IS F
           RECORD CONTAINS 80 CHARACTERS.
       01  PARM-REC.
           05  PARM-BRANCH         PIC X(4).
           05  PARM-RATE           PIC 9V9(4).
           05  FILLER              PIC X(71).
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL DECLARE BANK.ACCOUNT TABLE
               ( ACCT_ID        CHAR(10)       NOT NULL,
                 BRANCH_CD      CHAR(4)        NOT NULL,
                 BALANCE        DECIMAL(11, 2) NOT NULL,
                 LAST_ACTIVITY  DATE,
                 STATUS_CD      CHAR(1)        NOT NULL WITH DEFAULT
               ) END-EXEC.
       01  DCLACCOUNT.
           10  ACCT-ID             PIC X(10).
           10  BRANCH-CD           PIC X(4).
           10  BALANCE             PIC S9(9)V99 COMP-3.
           10  LAST-ACTIVITY       PIC X(10).
           10  STATUS-CD           PIC X(1).
       01  ACCOUNT-NULL-IND.
           10  IND-LAST-ACTIVITY   PIC S9(4) COMP.
       01  WS-HOST-ARRAYS.
           05  HA-ACCT-ID          PIC X(10) OCCURS 50 TIMES.
           05  HA-BALANCE          PIC S9(9)V99 COMP-3 OCCURS 50 TIMES.
       01  WS-ROWS-FETCHED         PIC S9(9) COMP.
       01  WS-PARM-STATUS          PIC XX.
       01  WS-COMMIT-COUNT         PIC 9(5) COMP VALUE 0.
       01  WS-NEW-BALANCE          PIC S9(9)V99 COMP-3.
       01  WS-EOF                  PIC X VALUE 'N'.
           88  END-OF-CURSOR       VALUE 'Y'.
       01  WS-ERROR-MESSAGE.
           05  WS-ERR-LEN          PIC S9(4) COMP VALUE 720.
           05  WS-ERR-TEXT         PIC X(72) OCCURS 10 TIMES.
       01  WS-ERR-LRECL            PIC S9(9) COMP VALUE 72.
           EXEC SQL DECLARE ACCT-CSR CURSOR WITH HOLD FOR
               SELECT ACCT_ID, BRANCH_CD, BALANCE, LAST_ACTIVITY,
                      STATUS_CD
                 FROM BANK.ACCOUNT
                WHERE BRANCH_CD = :PARM-BRANCH
                  AND STATUS_CD = 'A'
                FOR UPDATE OF BALANCE
           END-EXEC.
           EXEC SQL DECLARE BULK-CSR CURSOR WITH ROWSET POSITIONING FOR
               SELECT ACCT_ID, BALANCE
                 FROM BANK.ACCOUNT
                WHERE STATUS_CD = 'D'
           END-EXEC.
       PROCEDURE DIVISION.
       0000-MAIN.
           EXEC SQL WHENEVER SQLERROR GO TO 9900-SQL-ERROR END-EXEC
           EXEC SQL WHENEVER SQLWARNING CONTINUE END-EXEC
           OPEN INPUT PARM-FILE
           READ PARM-FILE
               AT END
                   DISPLAY 'NO PARAMETER CARD'
                   MOVE 16 TO RETURN-CODE
                   GOBACK
           END-READ
           PERFORM 1000-APPLY-RATE
           PERFORM 2000-BULK-REPORT
           EXEC SQL COMMIT END-EXEC
           CLOSE PARM-FILE
           GOBACK.
       1000-APPLY-RATE.
           EXEC SQL OPEN ACCT-CSR END-EXEC
           PERFORM UNTIL END-OF-CURSOR
               EXEC SQL FETCH ACCT-CSR
                   INTO :ACCT-ID, :BRANCH-CD, :BALANCE,
                        :LAST-ACTIVITY :IND-LAST-ACTIVITY,
                        :STATUS-CD
               END-EXEC
               EVALUATE SQLCODE
                   WHEN 0
                       PERFORM 1100-UPDATE-ROW
                   WHEN 100
                       SET END-OF-CURSOR TO TRUE
                   WHEN OTHER
                       PERFORM 9900-SQL-ERROR
               END-EVALUATE
           END-PERFORM
           EXEC SQL CLOSE ACCT-CSR END-EXEC.
       1100-UPDATE-ROW.
           COMPUTE WS-NEW-BALANCE ROUNDED = BALANCE * (1 + PARM-RATE)
           EXEC SQL UPDATE BANK.ACCOUNT
                  SET BALANCE = :WS-NEW-BALANCE,
                      LAST_ACTIVITY = CURRENT DATE
                WHERE CURRENT OF ACCT-CSR
           END-EXEC
           IF IND-LAST-ACTIVITY < 0
               DISPLAY 'FIRST ACTIVITY FOR ' ACCT-ID
           END-IF
           ADD 1 TO WS-COMMIT-COUNT
           IF WS-COMMIT-COUNT >= 100
               EXEC SQL COMMIT END-EXEC
               MOVE 0 TO WS-COMMIT-COUNT
           END-IF.
       2000-BULK-REPORT.
           EXEC SQL OPEN BULK-CSR END-EXEC
           EXEC SQL FETCH NEXT ROWSET FROM BULK-CSR
               FOR 50 ROWS
               INTO :HA-ACCT-ID, :HA-BALANCE
           END-EXEC
           MOVE SQLERRD(3) TO WS-ROWS-FETCHED
           DISPLAY 'DORMANT ACCOUNTS FETCHED: ' WS-ROWS-FETCHED
           EXEC SQL CLOSE BULK-CSR END-EXEC.
       9900-SQL-ERROR.
           DISPLAY 'SQLCODE=' SQLCODE ' SQLSTATE=' SQLSTATE
           CALL 'DSNTIAR' USING SQLCA WS-ERROR-MESSAGE WS-ERR-LRECL
           DISPLAY WS-ERR-TEXT(1)
           EXEC SQL ROLLBACK END-EXEC
           MOVE 12 TO RETURN-CODE
           GOBACK.
