       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTSUM.
      * STEP 2 OF CUSTJOB: TOTAL THE ACTIVE BALANCES
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACT-IN ASSIGN TO CUSTIN
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  ACT-IN.
       01  ACT-REC.
           COPY CUSTREC.
       WORKING-STORAGE SECTION.
       01  WS-FS                  PIC XX.
       01  WS-EOF                 PIC X VALUE 'N'.
       01  WS-COUNT               PIC 9(5) VALUE 0.
       01  WS-TOTAL               PIC S9(9)V99 VALUE 0.
       01  WS-TOTAL-ED            PIC -(9)9.99.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT ACT-IN
           PERFORM UNTIL WS-EOF = 'Y'
               READ ACT-IN
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       ADD CUST-BAL TO WS-TOTAL
               END-READ
           END-PERFORM
           CLOSE ACT-IN
           MOVE WS-TOTAL TO WS-TOTAL-ED
           DISPLAY 'CUSTSUM COUNT ' WS-COUNT ' TOTAL ' WS-TOTAL-ED
           IF WS-COUNT = 0
               MOVE 4 TO RETURN-CODE
           END-IF
           GOBACK.
