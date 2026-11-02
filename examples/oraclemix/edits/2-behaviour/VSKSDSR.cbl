       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSKSDSR.
      * KSDS RANDOM: ADD, CHANGE, DELETE ACCOUNTS
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRAN-FILE ASSIGN TO TRANIN
               FILE STATUS IS WS-TRAN-FS.
           SELECT ACCT-KSDS ASSIGN TO ACCTKSDS
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS AK-ID
               FILE STATUS IS WS-ACCT-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  TRAN-FILE.
       01  TRAN-REC.
           05  TR-CODE            PIC X.
           05  TR-ID              PIC 9(6).
           05  TR-NAME            PIC X(20).
           05  TR-AMOUNT          PIC S9(7)V99.
       FD  ACCT-KSDS.
       01  ACCT-REC.
           05  AK-ID              PIC 9(6).
           05  AK-NAME            PIC X(20).
           05  AK-BAL             PIC S9(7)V99.
       WORKING-STORAGE SECTION.
       01  WS-TRAN-FS             PIC XX.
       01  WS-ACCT-FS             PIC XX.
           88  ACCT-OK            VALUE '00'.
           88  ACCT-DUPKEY        VALUE '22'.
           88  ACCT-NOTFND        VALUE '23'.
       01  WS-EOF                 PIC X VALUE 'N'.
       01  WS-COUNTS.
           05  WS-ADDED           PIC 9(5) VALUE 0.
           05  WS-CHANGED         PIC 9(5) VALUE 0.
           05  WS-DELETED         PIC 9(5) VALUE 0.
           05  WS-REJECTED        PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT TRAN-FILE
           OPEN I-O ACCT-KSDS
           IF WS-ACCT-FS NOT = '00'
               DISPLAY 'VSKSDSR OPEN FAILED ' WS-ACCT-FS
               MOVE 16 TO RETURN-CODE
               GOBACK
           END-IF
           PERFORM UNTIL WS-EOF = 'Y'
               READ TRAN-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM 1000-APPLY
               END-READ
           END-PERFORM
           CLOSE TRAN-FILE ACCT-KSDS
           DISPLAY 'VSKSDSR ADDED ' WS-ADDED ' CHANGED ' WS-CHANGED
               ' DELETED ' WS-DELETED ' REJECTED ' WS-REJECTED
           IF WS-REJECTED > 0
               MOVE 4 TO RETURN-CODE
           END-IF
           GOBACK.
       1000-APPLY.
           EVALUATE TR-CODE
               WHEN 'A'
                   PERFORM 2000-ADD
               WHEN 'C'
                   PERFORM 3000-CHANGE
               WHEN 'D'
                   PERFORM 4000-DELETE
               WHEN OTHER
                   ADD 1 TO WS-REJECTED
           END-EVALUATE.
       2000-ADD.
           MOVE TR-ID TO AK-ID
           MOVE TR-NAME TO AK-NAME
           MOVE TR-AMOUNT TO AK-BAL
           WRITE ACCT-REC
               INVALID KEY
                   DISPLAY 'DUPLICATE ' TR-ID
                   ADD 1 TO WS-REJECTED
               NOT INVALID KEY
                   ADD 1 TO WS-ADDED
           END-WRITE.
       3000-CHANGE.
           MOVE TR-ID TO AK-ID
           READ ACCT-KSDS
           IF ACCT-NOTFND
               DISPLAY 'NO ACCOUNT ' TR-ID
               ADD 1 TO WS-REJECTED
           ELSE
               ADD TR-AMOUNT TO AK-BAL
               REWRITE ACCT-REC
               IF ACCT-OK
                   ADD 1 TO WS-CHANGED
               ELSE
                   DISPLAY 'REWRITE FAILED ' WS-ACCT-FS
                   ADD 1 TO WS-REJECTED
               END-IF
           END-IF.
       4000-DELETE.
           MOVE TR-ID TO AK-ID
           DELETE ACCT-KSDS RECORD
               INVALID KEY
                   ADD 1 TO WS-REJECTED
               NOT INVALID KEY
                   ADD 1 TO WS-DELETED
           END-DELETE.
