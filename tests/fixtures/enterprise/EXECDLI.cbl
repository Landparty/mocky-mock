       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECDLI.
      *================================================================*
      * Program type: IMS program using the EXEC DLI command interface *
      * (the CICS-DBCTL / IMS command-level style), with SCHD PSB,     *
      * qualified GU/GN/REPL/ISRT via SEGMENT/WHERE clauses, DIB       *
      * status checking and TERM.                                      *
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CUST-ID              PIC X(8).
       01  CUST-AREA.
           05  CUST-ID             PIC X(8).
           05  CUST-NAME           PIC X(30).
           05  CUST-STATUS         PIC X.
       01  ACCT-AREA.
           05  ACCT-NO             PIC X(10).
           05  ACCT-BALANCE        PIC S9(9)V99 COMP-3.
       01  WS-ACCT-COUNT           PIC 9(5) COMP VALUE 0.
       01  WS-DONE                 PIC X VALUE 'N'.
           88  DONE                VALUE 'Y'.
       PROCEDURE DIVISION.
       0000-MAIN.
           EXEC DLI SCHD PSB(CUSTPSB) END-EXEC
           IF DIBSTAT NOT = '  '
               DISPLAY 'SCHD FAILED ' DIBSTAT
               GOBACK
           END-IF
           MOVE 'C0001234' TO WS-CUST-ID
           EXEC DLI GU USING PCB(1)
               SEGMENT(CUSTSEG) INTO(CUST-AREA)
               WHERE(CUSTID = WS-CUST-ID)
           END-EXEC
           EVALUATE DIBSTAT
               WHEN '  '
                   PERFORM 1000-SCAN-ACCOUNTS
               WHEN 'GE'
                   DISPLAY 'CUSTOMER NOT FOUND'
               WHEN OTHER
                   DISPLAY 'GU STATUS ' DIBSTAT
           END-EVALUATE
           EXEC DLI TERM END-EXEC
           GOBACK.
       1000-SCAN-ACCOUNTS.
           PERFORM UNTIL DONE
               EXEC DLI GNP USING PCB(1)
                   SEGMENT(ACCTSEG) INTO(ACCT-AREA)
               END-EXEC
               IF DIBSTAT = '  '
                   ADD 1 TO WS-ACCT-COUNT
                   IF ACCT-BALANCE < 0
                       PERFORM 1100-FLAG-OVERDRAWN
                   END-IF
               ELSE
                   SET DONE TO TRUE
               END-IF
           END-PERFORM
           IF WS-ACCT-COUNT = 0
               MOVE 'N' TO CUST-STATUS
               EXEC DLI GHU USING PCB(1)
                   SEGMENT(CUSTSEG) INTO(CUST-AREA)
                   WHERE(CUSTID = WS-CUST-ID)
               END-EXEC
               EXEC DLI REPL FROM(CUST-AREA) END-EXEC
           END-IF.
       1100-FLAG-OVERDRAWN.
           EXEC DLI GHN USING PCB(1)
               SEGMENT(ACCTSEG) INTO(ACCT-AREA)
           END-EXEC
           MOVE 0 TO ACCT-BALANCE
           EXEC DLI REPL FROM(ACCT-AREA) END-EXEC
           IF DIBSTAT NOT = '  '
               DISPLAY 'REPL FAILED ' DIBSTAT
           END-IF
           EXEC DLI ISRT USING PCB(1)
               SEGMENT(CUSTSEG) WHERE(CUSTID = WS-CUST-ID)
               SEGMENT(NOTESEG) FROM(ACCT-AREA)
           END-EXEC.
