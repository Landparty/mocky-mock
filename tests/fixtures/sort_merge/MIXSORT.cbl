       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIXSORT.
      * A SORT reading a real file (USING) and writing through an
      * OUTPUT PROCEDURE that stops the run at a "STOP" record.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "INFILE"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT SORT-FILE ASSIGN TO "SRTWK".
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC             PIC X(4).
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
               USING IN-FILE
               OUTPUT PROCEDURE IS EMIT-PARA THRU EMIT-EXIT
           MOVE "DONE" TO WS-LAST.
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
