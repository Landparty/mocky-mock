       IDENTIFICATION DIVISION.
       PROGRAM-ID. DB2SP.
      *================================================================*
      * Program type: DB2 external stored procedure (WLM-managed).     *
      * Parameters and their null indicators arrive on PROCEDURE       *
      * DIVISION USING, results come back through a WITH RETURN cursor *
      * and the SQLSTATE / DIAGNOSTIC output parameters.               *
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-BALANCE              PIC S9(9)V99 COMP-3.
       01  WS-COUNT                PIC S9(9) COMP.
       LINKAGE SECTION.
       01  P-CUST-ID               PIC X(8).
       01  P-MIN-BALANCE           PIC S9(9)V99 COMP-3.
       01  P-TOTAL-BALANCE         PIC S9(11)V99 COMP-3.
       01  P-ACCT-COUNT            PIC S9(9) COMP.
       01  P-IND-CUST-ID           PIC S9(4) COMP.
       01  P-IND-MIN-BALANCE       PIC S9(4) COMP.
       01  P-IND-TOTAL-BALANCE     PIC S9(4) COMP.
       01  P-IND-ACCT-COUNT        PIC S9(4) COMP.
       01  P-SQLSTATE              PIC X(5).
       01  P-PROC-NAME             PIC X(27).
       01  P-SPEC-NAME             PIC X(18).
       01  P-DIAG-MSG              PIC X(70).
       PROCEDURE DIVISION USING P-CUST-ID P-MIN-BALANCE
                                P-TOTAL-BALANCE P-ACCT-COUNT
                                P-IND-CUST-ID P-IND-MIN-BALANCE
                                P-IND-TOTAL-BALANCE P-IND-ACCT-COUNT
                                P-SQLSTATE P-PROC-NAME P-SPEC-NAME
                                P-DIAG-MSG.
       0000-MAIN.
           MOVE SPACES TO P-DIAG-MSG
           IF P-IND-CUST-ID < 0
               MOVE '38001' TO P-SQLSTATE
               MOVE 'CUSTOMER ID IS REQUIRED' TO P-DIAG-MSG
               GOBACK
           END-IF
           IF P-IND-MIN-BALANCE < 0
               MOVE ZERO TO P-MIN-BALANCE
           END-IF
           EXEC SQL
               SELECT SUM(BALANCE), COUNT(*)
                 INTO :WS-BALANCE, :WS-COUNT
                 FROM BANK.ACCOUNT
                WHERE CUST_ID = :P-CUST-ID
                  AND BALANCE >= :P-MIN-BALANCE
           END-EXEC
           EVALUATE SQLCODE
               WHEN 0
                   MOVE WS-BALANCE TO P-TOTAL-BALANCE
                   MOVE WS-COUNT TO P-ACCT-COUNT
                   MOVE 0 TO P-IND-TOTAL-BALANCE P-IND-ACCT-COUNT
                   PERFORM 1000-OPEN-RESULT-SET
               WHEN 100
                   MOVE -1 TO P-IND-TOTAL-BALANCE
                   MOVE 0 TO P-ACCT-COUNT
                   MOVE 0 TO P-IND-ACCT-COUNT
               WHEN OTHER
                   MOVE SQLSTATE TO P-SQLSTATE
                   MOVE 'ACCOUNT LOOKUP FAILED' TO P-DIAG-MSG
           END-EVALUATE
           GOBACK.
       1000-OPEN-RESULT-SET.
           EXEC SQL DECLARE ACCT-RS CURSOR WITH RETURN FOR
               SELECT ACCT_ID, BALANCE, STATUS_CD
                 FROM BANK.ACCOUNT
                WHERE CUST_ID = :P-CUST-ID
                ORDER BY BALANCE DESC
           END-EXEC
           EXEC SQL OPEN ACCT-RS END-EXEC
           IF SQLCODE NOT = 0
               MOVE SQLSTATE TO P-SQLSTATE
               MOVE 'RESULT SET OPEN FAILED' TO P-DIAG-MSG
           END-IF.
