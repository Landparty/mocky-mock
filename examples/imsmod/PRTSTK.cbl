       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRTSTK.
      * Stock on hand for a part, from DB2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-PART                 PIC X(8).
       01  WS-QTY                  PIC S9(9) COMP VALUE 0.
       LINKAGE SECTION.
       01  LK-PART                 PIC X(8).
       01  LK-ONHAND               PIC 9(7).
       01  LK-RC                   PIC 9(2).
       PROCEDURE DIVISION USING LK-PART LK-ONHAND LK-RC.
       0000-LOOKUP.
           MOVE LK-PART TO WS-PART
           EXEC SQL
               SELECT QTY_ON_HAND INTO :WS-QTY
                 FROM PART_STOCK
                WHERE PART_NO = :WS-PART
           END-EXEC
           IF SQLCODE = 0
               MOVE WS-QTY TO LK-ONHAND
               MOVE 0 TO LK-RC
           ELSE
               MOVE 0 TO LK-ONHAND
               MOVE 8 TO LK-RC
           END-IF
           GOBACK.
