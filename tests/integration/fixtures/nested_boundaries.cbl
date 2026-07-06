       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTBND.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MODE            PIC X VALUE "B".
       01  WS-DISC-RATE       PIC 9(3) VALUE 0.
       01  WS-TAX-RATE        PIC 9(3) VALUE 0.
       01  WS-SQL-STATUS      PIC XX VALUE SPACES.
       01  SQLCODE            PIC S9(9) COMP VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           IF WS-MODE = "B"
               CALL "DISCRATE"
                   USING WS-DISC-RATE
           END-IF.
           EVALUATE WS-MODE
               WHEN "B"
                   CALL "TAXCALC" USING WS-TAX-RATE
               WHEN OTHER
                   MOVE 0 TO WS-TAX-RATE
           END-EVALUATE.
           IF WS-MODE = "B"
               EXEC SQL
                   UPDATE ORDERS SET STATUS = 'B' WHERE ID = 1
               END-EXEC
               IF SQLCODE = 0
                   MOVE "OK" TO WS-SQL-STATUS
               END-IF
           END-IF.
