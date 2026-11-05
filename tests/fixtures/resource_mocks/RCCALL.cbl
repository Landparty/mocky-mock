       IDENTIFICATION DIVISION.
       PROGRAM-ID. RCCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM       PIC X(8) VALUE "DYNLOG".
       01  WS-MSG       PIC X(20) VALUE SPACES.
       PROCEDURE DIVISION.
       STATIC-PARA.
           MOVE 8 TO RETURN-CODE
           CALL "LOGIT" USING WS-MSG
           IF RETURN-CODE = 0
               MOVE "RC-RESET" TO WS-MSG
           ELSE
               MOVE "RC-KEPT" TO WS-MSG
           END-IF.
       DYNAMIC-PARA.
           MOVE 8 TO RETURN-CODE
           CALL WS-PGM USING WS-MSG
           IF RETURN-CODE = 0
               MOVE "RC-RESET" TO WS-MSG
           ELSE
               MOVE "RC-KEPT" TO WS-MSG
           END-IF.
