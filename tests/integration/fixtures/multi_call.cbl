       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CALLS   PIC 9(3) VALUE 0.
       01 WS-LAST    PIC X(8) VALUE SPACES.
       01 WS-IN      PIC X(8).
       01 WS-STATUS  PIC XX.
       PROCEDURE DIVISION.
       0000-ENTRY.
           ADD 1 TO WS-CALLS
           IF WS-IN = WS-LAST
               MOVE "DU" TO WS-STATUS
           ELSE
               MOVE "OK" TO WS-STATUS
               MOVE WS-IN TO WS-LAST
           END-IF
           CALL "AUDIT" USING WS-IN
           GOBACK.
