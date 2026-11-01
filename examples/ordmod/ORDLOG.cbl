       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDLOG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOG-FILE ASSIGN TO ORDLOG
               FILE STATUS IS WS-LOG-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  LOG-FILE.
       01  LOG-LINE                PIC X(50).
       WORKING-STORAGE SECTION.
       01  WS-LOG-FS               PIC XX.
       01  WS-LINES                PIC 9(5) VALUE 0.
       LINKAGE SECTION.
       01  LK-ORD-ID               PIC X(6).
       01  LK-MSG                  PIC X(40).
       PROCEDURE DIVISION USING LK-ORD-ID LK-MSG.
       0000-LOG.
           OPEN EXTEND LOG-FILE
           MOVE SPACES TO LOG-LINE
           STRING LK-ORD-ID DELIMITED BY SIZE
                  " " DELIMITED BY SIZE
                  LK-MSG DELIMITED BY SIZE
                  INTO LOG-LINE
           WRITE LOG-LINE
           CLOSE LOG-FILE
           ADD 1 TO WS-LINES
           GOBACK.
