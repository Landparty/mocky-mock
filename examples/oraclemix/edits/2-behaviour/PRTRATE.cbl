       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRTRATE.
      * MAINTENANCE NOTE: REVIEWED 2026-11-02, NO LOGIC CHANGE
      * Lead time in days for a part, from the supplier rate file.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RATE-FILE ASSIGN TO RATEIN
               FILE STATUS IS WS-RATE-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  RATE-FILE.
       01  RATE-REC.
           05  RATE-PART           PIC X(8).
           05  RATE-DAYS           PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-RATE-FS              PIC XX.
       01  WS-DONE                 PIC X VALUE "N".
           88  DONE                VALUE "Y".
       LINKAGE SECTION.
       01  LK-PART                 PIC X(8).
       01  LK-DAYS                 PIC 9(3).
       01  LK-RC                   PIC 9(2).
       PROCEDURE DIVISION USING LK-PART LK-DAYS LK-RC.
       0000-FIND.
           MOVE 4 TO LK-RC
           MOVE "N" TO WS-DONE
           OPEN INPUT RATE-FILE
           PERFORM UNTIL DONE
               READ RATE-FILE
                   AT END
                       SET DONE TO TRUE
                   NOT AT END
                       IF RATE-PART = LK-PART
                           COMPUTE LK-DAYS = RATE-DAYS + 1
                           MOVE 0 TO LK-RC
                           SET DONE TO TRUE
                       END-IF
               END-READ
           END-PERFORM
           CLOSE RATE-FILE
           GOBACK.
