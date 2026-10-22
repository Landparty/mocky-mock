       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMEDIT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT              PIC S9(9)V99 VALUE 0.
       01  WS-DET-BAL             PIC Z,ZZZ,ZZZ,ZZ9.99.
       01  WS-DET-NET             PIC ZZ,ZZ9.99CR.
       01  WS-DET-CHK             PIC $***,**9.99.
       01  WS-ROW.
           05  WS-ROW-AMT         PIC -ZZ9.99 OCCURS 2 TIMES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 100 TO WS-AMOUNT
           MOVE WS-AMOUNT TO WS-DET-BAL
           MOVE -1234.5 TO WS-DET-NET
           MOVE 42.1 TO WS-DET-CHK
           MOVE -7.25 TO WS-ROW-AMT (2)
           GOBACK.
