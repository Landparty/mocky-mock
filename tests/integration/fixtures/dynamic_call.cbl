       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNCALL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE SPACES.
       01  WS-FLAG            PIC X VALUE "Y".
       01  WS-RC              PIC 9(4) VALUE 0.
       01  WS-TOTAL           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           MOVE "PGMA" TO WS-PGM-NAME.
           CALL WS-PGM-NAME USING WS-RC.
           ADD WS-RC TO WS-TOTAL.
           MOVE "PGMB" TO WS-PGM-NAME.
           CALL WS-PGM-NAME USING WS-RC.
           ADD WS-RC TO WS-TOTAL.
           IF WS-FLAG = "Y"
               CALL WS-PGM-NAME USING WS-RC
           END-IF.
           ADD WS-RC TO WS-TOTAL.
