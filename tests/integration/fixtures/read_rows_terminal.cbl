       IDENTIFICATION DIVISION.
       PROGRAM-ID. RDROWST.
      * Sequential file READ loop driven end-to-end by a MOCK READ
      * ... ROWS ... TERMINAL directive: no FILE STATUS field on
      * INV-FILE, so the loop's only way to reach WS-EOF = "Y" is the
      * TERMINAL group's own MOVE, spliced into the READ site's
      * WHEN OTHER branch.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-QTY        PIC 9(5).

       WORKING-STORAGE SECTION.
       01  WS-EOF             PIC X     VALUE "N".
       01  WS-TOTAL-QTY       PIC 9(7)  VALUE 0.
       01  WS-ROW-COUNT       PIC 9(4)  VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE.
           PERFORM READ-LOOP UNTIL WS-EOF = "Y".
           CLOSE INV-FILE.
           STOP RUN.

       READ-LOOP.
           READ INV-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ.
           IF WS-EOF = "N"
               ADD INV-QTY TO WS-TOTAL-QTY
               ADD 1 TO WS-ROW-COUNT
           END-IF.
