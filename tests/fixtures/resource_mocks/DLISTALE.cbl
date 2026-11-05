       IDENTIFICATION DIVISION.
       PROGRAM-ID. DLISTALE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SEG-AREA     PIC X(20).
       01  WS-COUNT     PIC 9(4) VALUE 0.
       01  WS-MSG       PIC X(20) VALUE SPACES.
       LINKAGE SECTION.
       01  DFHCOMMAREA  PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC DLI SCHD PSB(MYPSB) END-EXEC
           PERFORM UNTIL DIBSTAT NOT = SPACES
               EXEC DLI GN USING PCB(1) SEGMENT(ORDER) INTO(SEG-AREA)
               END-EXEC
               IF DIBSTAT = SPACES
                   ADD 1 TO WS-COUNT
               END-IF
           END-PERFORM
           EXEC DLI TERM END-EXEC
           IF DIBSTAT = SPACES
               MOVE "TERM-OK" TO WS-MSG
           ELSE
               MOVE "TERM-BAD" TO WS-MSG
           END-IF
           GOBACK.
