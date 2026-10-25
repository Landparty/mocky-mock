       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUGOTO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMT     PIC S9(5) VALUE 0.
       01 WS-TOTAL   PIC S9(7) VALUE 0.
       01 WS-REJECTS PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           PERFORM 3000-POST THRU 3400-POST-EXIT
           PERFORM 4000-REPORT
           GOBACK.
       1000-INIT.
           MOVE 0 TO WS-TOTAL.
       3000-POST.
           IF WS-AMT < 0
               ADD 1 TO WS-REJECTS
               GO TO 3400-POST-EXIT
           END-IF.
       3100-ADD.
           ADD WS-AMT TO WS-TOTAL.
       3400-POST-EXIT.
           EXIT.
       4000-REPORT.
           ADD 1 TO WS-TOTAL.
       9000-OTHER.
           MOVE 1 TO WS-TOTAL.
