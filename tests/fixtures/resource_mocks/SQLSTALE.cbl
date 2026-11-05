       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLSTALE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-NAME     PIC X(10).
       01  WS-COUNT    PIC 9(4) VALUE 0.
       01  WS-RESULT   PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL OPEN C1 END-EXEC
           PERFORM UNTIL SQLCODE NOT = 0
               EXEC SQL FETCH C1 INTO :WS-NAME END-EXEC
               IF SQLCODE = 0
                   ADD 1 TO WS-COUNT
               END-IF
           END-PERFORM
           EXEC SQL CLOSE C1 END-EXEC
           IF SQLCODE = 0
               MOVE "CLOSED-OK" TO WS-RESULT
           ELSE
               MOVE "CLOSE-ERR" TO WS-RESULT
           END-IF
           GOBACK.
