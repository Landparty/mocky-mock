       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTUPD.
      * APPLIES TRANSACTIONS TO THE VSAM KSDS CUSTOMER MASTER
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRAN-FILE ASSIGN TO TRANIN
               FILE STATUS IS WS-TRAN-FS.
           SELECT ACCT-MAST ASSIGN TO ACCTMAST
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS CUST-ID
               FILE STATUS IS WS-MAST-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  TRAN-FILE.
       01  TRAN-REC.
           05  TR-CUST-ID         PIC 9(6).
           05  TR-AMOUNT          PIC S9(7)V99.
       FD  ACCT-MAST.
       01  MAST-REC.
           COPY CUSTREC.
       WORKING-STORAGE SECTION.
       01  WS-TRAN-FS             PIC XX.
       01  WS-MAST-FS             PIC XX.
       01  WS-EOF                 PIC X VALUE 'N'.
       01  WS-APPLIED             PIC 9(5) VALUE 0.
       01  WS-MISSING             PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT TRAN-FILE
           OPEN I-O ACCT-MAST
           PERFORM UNTIL WS-EOF = 'Y'
               READ TRAN-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM 1000-APPLY
               END-READ
           END-PERFORM
           CLOSE TRAN-FILE
           CLOSE ACCT-MAST
           DISPLAY 'ACCTUPD APPLIED ' WS-APPLIED ' MISSING ' WS-MISSING
           IF WS-MISSING > 0
               MOVE 4 TO RETURN-CODE
           END-IF
           GOBACK.
       1000-APPLY.
           MOVE TR-CUST-ID TO CUST-ID
           READ ACCT-MAST
               INVALID KEY
                   ADD 1 TO WS-MISSING
               NOT INVALID KEY
                   COMPUTE CUST-BAL = CUST-BAL - TR-AMOUNT
                   REWRITE MAST-REC
                   ADD 1 TO WS-APPLIED
           END-READ.
