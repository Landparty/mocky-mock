       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MODE            PIC X VALUE "A".
       01  WS-PATH            PIC X(4) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-MODE = "B"
               ALTER SWITCH-PARA TO PROCEED TO PATH-B
           END-IF
           PERFORM SWITCH-PARA THRU SWITCH-EXIT.
       SWITCH-PARA.
           GO TO PATH-A.
       PATH-A.
           MOVE "A" TO WS-PATH
           GO TO SWITCH-EXIT.
       PATH-B.
           MOVE "B" TO WS-PATH.
       SWITCH-EXIT.
           EXIT.
