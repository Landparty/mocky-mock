       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTEXT.
      * Step 1 of CUSTJOB: copies the customers whose balance is over
      * the limit to CUSTOUT, and logs the run to DB2.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-IN ASSIGN TO CUSTIN
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-IN-STATUS.
           SELECT CUST-OUT ASSIGN TO UT-S-CUSTOUT
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-IN
           RECORDING MODE IS F.
       01  CUST-IN-REC.
           05  CI-ID              PIC 9(5).
           05  CI-NAME            PIC X(10).
           05  CI-BALANCE         PIC 9(5).
       FD  CUST-OUT
           RECORDING MODE IS F.
       01  CUST-OUT-REC           PIC X(20).
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-IN-STATUS           PIC XX VALUE "00".
       01  WS-EOF                 PIC X VALUE "N".
       01  WS-LIMIT               PIC 9(5) VALUE 100.
       01  WS-READ                PIC 9(5) VALUE 0.
       01  WS-KEPT                PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CUST-IN
           IF WS-IN-STATUS NOT = "00"
               MOVE 12 TO RETURN-CODE
               GOBACK
           END-IF
           OPEN OUTPUT CUST-OUT
           PERFORM READ-PARA
           PERFORM UNTIL WS-EOF = "Y"
               ADD 1 TO WS-READ
               IF CI-BALANCE > WS-LIMIT
                   MOVE CUST-IN-REC TO CUST-OUT-REC
                   WRITE CUST-OUT-REC
                   ADD 1 TO WS-KEPT
               END-IF
               PERFORM READ-PARA
           END-PERFORM
           CLOSE CUST-IN CUST-OUT
           EXEC SQL
               INSERT INTO RUNLOG (PGM, KEPT)
                   VALUES ('CUSTEXT', :WS-KEPT)
           END-EXEC
           IF WS-KEPT = 0
               MOVE 4 TO RETURN-CODE
           END-IF
           GOBACK.
       READ-PARA.
           READ CUST-IN
               AT END MOVE "Y" TO WS-EOF
           END-READ.
