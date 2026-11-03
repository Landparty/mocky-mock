       IDENTIFICATION DIVISION.
       PROGRAM-ID.
           NESTCALL.
      * The outer program CALLs the program nested in it; a GO TO
      * target's STOP RUN needs the driver's call frame.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC              PIC 9(2) VALUE 0.
       01  WS-STEP            PIC X(4) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "CALL" TO WS-STEP
           CALL "INNER" USING WS-RC
           IF WS-RC > 4
               GO TO ABEND-PARA
           END-IF
           MOVE "DONE" TO WS-STEP.
       MAIN-EXIT.
           EXIT.
       ABEND-PARA.
           MOVE "FAIL" TO WS-STEP
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-RC              PIC 9(2).
       PROCEDURE DIVISION USING LK-RC.
       INNER-PARA.
           MOVE 8 TO LK-RC
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM NESTCALL.
