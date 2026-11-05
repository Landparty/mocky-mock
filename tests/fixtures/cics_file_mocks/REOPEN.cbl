       IDENTIFICATION DIVISION.
       PROGRAM-ID. REOPEN.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEQF ASSIGN TO SEQF
               FILE STATUS IS WS-SFS.
       DATA DIVISION.
       FILE SECTION.
       FD  SEQF.
       01  S-REC      PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-SFS     PIC XX VALUE "00".
       01  WS-N1      PIC 9(4) VALUE 0.
       01  WS-N2      PIC 9(4) VALUE 0.
       01  WS-FIRST2  PIC X(20) VALUE SPACES.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-NAME    PIC X(10).
       01  WS-C1      PIC 9(4) VALUE 0.
       01  WS-C2      PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       TWO-PASS.
           OPEN INPUT SEQF
           PERFORM UNTIL WS-SFS = "10"
               READ SEQF
               IF WS-SFS = "00" ADD 1 TO WS-N1 END-IF
           END-PERFORM
           CLOSE SEQF
           OPEN INPUT SEQF
           MOVE "00" TO WS-SFS
           PERFORM UNTIL WS-SFS = "10"
               READ SEQF
               IF WS-SFS = "00"
                   ADD 1 TO WS-N2
                   IF WS-N2 = 1 MOVE S-REC TO WS-FIRST2 END-IF
               END-IF
           END-PERFORM
           CLOSE SEQF.
       CURSOR-TWICE.
           EXEC SQL DECLARE C1 CURSOR FOR SELECT NAME FROM T END-EXEC
           EXEC SQL OPEN C1 END-EXEC
           PERFORM UNTIL SQLCODE = 100
               EXEC SQL FETCH C1 INTO :WS-NAME END-EXEC
               IF SQLCODE = 0 ADD 1 TO WS-C1 END-IF
           END-PERFORM
           EXEC SQL CLOSE C1 END-EXEC
           EXEC SQL OPEN C1 END-EXEC
           PERFORM UNTIL SQLCODE = 100
               EXEC SQL FETCH C1 INTO :WS-NAME END-EXEC
               IF SQLCODE = 0 ADD 1 TO WS-C2 END-IF
           END-PERFORM
           EXEC SQL CLOSE C1 END-EXEC.
