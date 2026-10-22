       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLTHRU.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                   PIC 9 VALUE 0.
       01  WS-Y                   PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM PROCESS-REC
           PERFORM WRITE-REPORT
           GOBACK.
       PROCESS-REC.
           IF WS-X = 1
               GO TO PROCESS-SKIP
           END-IF
           CALL "CALC" USING WS-Y.
       PROCESS-SKIP.
           ADD 1 TO WS-Y.
       WRITE-REPORT.
           CALL "REPORTER" USING WS-Y.
