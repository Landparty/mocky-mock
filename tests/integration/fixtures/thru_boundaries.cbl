       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUBND.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS           PIC X(2)  VALUE SPACES.
       01  WS-RATE             PIC 9V99  VALUE 0.
       01  WS-TOTAL            PIC 9(5)  VALUE 0.

       PROCEDURE DIVISION.
       MAIN-DRIVER.
           PERFORM PROCESS-ORDER THRU PROCESS-EXIT.
           STOP RUN.

       PROCESS-ORDER.
           CALL "RATELKP" USING WS-RATE.
           IF WS-RATE = 0
               MOVE "ER" TO WS-STATUS
               GO TO PROCESS-EXIT
           END-IF.

       PROCESS-APPLY.
           CALL "TOTCALC" USING WS-RATE WS-TOTAL.
           MOVE "OK" TO WS-STATUS.

       PROCESS-EXIT.
           EXIT.
