       IDENTIFICATION DIVISION.
       PROGRAM-ID. PURESORT.
      * A SORT with both procedures, left real, whose OUTPUT PROCEDURE
      * stops the run at a "STOP" record: the GOBACK to the test leaves
      * the active sort, and the next case's SORT runs from the start.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-FILE ASSIGN TO "SRTWK".
       DATA DIVISION.
       FILE SECTION.
       SD  SORT-FILE.
       01  SORT-REC.
           05  SORT-KEY       PIC X(4).
       WORKING-STORAGE SECTION.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-COUNT           PIC 9(2) VALUE 0.
       01  WS-LAST            PIC X(4) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "N" TO WS-EOF
           MOVE 0 TO WS-COUNT
           SORT SORT-FILE ON ASCENDING KEY SORT-KEY
               INPUT PROCEDURE IS FEED-PARA
               OUTPUT PROCEDURE IS EMIT-PARA THRU EMIT-EXIT
           MOVE "DONE" TO WS-LAST.
       FEED-PARA.
           MOVE "AAAA" TO SORT-KEY
           RELEASE SORT-REC.
       EMIT-PARA.
           PERFORM UNTIL WS-EOF = "Y"
               RETURN SORT-FILE
                   AT END
                       MOVE "Y" TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       MOVE SORT-KEY TO WS-LAST
                       IF SORT-KEY = "STOP"
                           GO TO STOP-PARA
                       END-IF
               END-RETURN
           END-PERFORM.
       EMIT-EXIT.
           EXIT.
       STOP-PARA.
           STOP RUN.
