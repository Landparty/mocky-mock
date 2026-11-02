       IDENTIFICATION DIVISION.
       PROGRAM-ID. DB2RPT.
      * REGION REPORT FROM DB2: CURSOR, THEN A RUN-LOG UPDATE
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO RPTOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE.
       01  RPT-LINE               PIC X(60).
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-CUST.
           COPY CUSTREC.
       01  WS-REGION              PIC X(4) VALUE 'EAST'.
       01  WS-COUNT               PIC S9(5) COMP-3 VALUE 0.
       01  WS-TOTAL               PIC S9(9)V99 COMP-3 VALUE 0.
       01  WS-BAL-ED              PIC -(7)9.99.
           EXEC SQL DECLARE CUSTCUR CURSOR FOR
               SELECT CUST_ID, CUST_NAME, CUST_BAL
                 FROM CUSTOMER
                WHERE REGION = :WS-REGION
           END-EXEC.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN OUTPUT RPT-FILE
           EXEC SQL OPEN CUSTCUR END-EXEC
           PERFORM UNTIL SQLCODE NOT = 0
               EXEC SQL FETCH CUSTCUR
                   INTO :CUST-ID, :CUST-NAME, :CUST-BAL
               END-EXEC
               IF SQLCODE = 0
                   ADD 1 TO WS-COUNT
                   ADD CUST-BAL TO WS-TOTAL
                   MOVE CUST-BAL TO WS-BAL-ED
                   MOVE SPACES TO RPT-LINE
                   STRING CUST-ID ' ' CUST-NAME ' ' WS-BAL-ED
                       DELIMITED BY SIZE INTO RPT-LINE
                   WRITE RPT-LINE
               END-IF
           END-PERFORM
           EXEC SQL CLOSE CUSTCUR END-EXEC
           EXEC SQL
               UPDATE RUNLOG
                  SET LAST_TOTAL = :WS-TOTAL
                WHERE REGION = :WS-REGION
           END-EXEC
           IF SQLCODE NOT = 0
               MOVE 8 TO RETURN-CODE
           END-IF
           CLOSE RPT-FILE
           DISPLAY 'DB2RPT ROWS ' WS-COUNT
           GOBACK.
