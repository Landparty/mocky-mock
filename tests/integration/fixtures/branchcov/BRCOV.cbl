       IDENTIFICATION DIVISION.
       PROGRAM-ID. BRCOV.
      * Branch coverage fixture: IF with and without ELSE, EVALUATE
      * with and without WHEN OTHER, an empty ELSE, a never-run
      * paragraph.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CODE            PIC 9 VALUE 0.
       01  WS-OUT             PIC X(8) VALUE SPACES.
       01  WS-FLAG            PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-CODE = 1
               MOVE "ONE" TO WS-OUT
           END-IF
           IF WS-FLAG = "Y"
               MOVE "FLAG" TO WS-OUT
           ELSE
               CONTINUE
           END-IF
           EVALUATE WS-CODE
               WHEN 1
                   MOVE "E1" TO WS-OUT
               WHEN 2
               WHEN 3
                   MOVE "E23" TO WS-OUT
               WHEN OTHER
                   MOVE "EO" TO WS-OUT
           END-EVALUATE
           EVALUATE TRUE
               WHEN WS-FLAG = "Y"
                   PERFORM FLAG-PARA
           END-EVALUATE
           GOBACK.
       FLAG-PARA.
           MOVE "F" TO WS-OUT.
       NEVER-PARA.
           MOVE "N" TO WS-OUT.
