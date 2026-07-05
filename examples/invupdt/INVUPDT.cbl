       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVUPDT.
      * Inventory updater exercising every mockable boundary category:
      * sequential file READ loop + report WRITE, DB2 UPDATE via EXEC
      * SQL, an MQ notification via CALL "MQPUT", and an operator
      * confirmation via console ACCEPT.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT RPT-FILE ASSIGN TO "RPT.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-ITEM-ID    PIC 9(5).
           05  INV-QTY        PIC 9(5).
       FD  RPT-FILE.
       01  RPT-REC            PIC X(40).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-TOTAL-QTY       PIC 9(7) VALUE 0.
       01  WS-REC-COUNT       PIC 9(4) VALUE 0.
       01  WS-SQL-STATUS      PIC X(4) VALUE "NONE".
       01  WS-CONFIRM         PIC X VALUE SPACE.
       01  MQ-COMPCODE        PIC S9(9) COMP-5 VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE OUTPUT RPT-FILE.
           PERFORM PROCESS-LOOP UNTIL WS-EOF = "Y".
           PERFORM UPDATE-DB.
           PERFORM NOTIFY-QUEUE.
           PERFORM ASK-CONFIRM.
           CLOSE INV-FILE RPT-FILE.

       PROCESS-LOOP.
           READ INV-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ.
           IF WS-EOF = "N"
               PERFORM TALLY-RECORD
           END-IF.

       TALLY-RECORD.
           ADD INV-QTY TO WS-TOTAL-QTY.
           ADD 1 TO WS-REC-COUNT.
           WRITE RPT-REC.

       UPDATE-DB.
           EXEC SQL
               UPDATE INVENTORY SET TOTAL_QTY = :WS-TOTAL-QTY
           END-EXEC.
           IF SQLCODE = 0
               MOVE "OK" TO WS-SQL-STATUS
           ELSE
               MOVE "FAIL" TO WS-SQL-STATUS
           END-IF.

       NOTIFY-QUEUE.
           CALL "MQPUT" USING MQ-COMPCODE.

       ASK-CONFIRM.
           ACCEPT WS-CONFIRM.
