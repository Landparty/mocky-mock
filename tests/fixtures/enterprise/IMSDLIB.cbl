       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSDLIB.
      *================================================================*
      * Program type: IMS DL/I batch (DLIBATCH / DBB region).          *
      * ENTRY 'DLITCBL' with PCB masks in LINKAGE, qualified and       *
      * unqualified SSAs, GU/GN/GNP/GHU/REPL/ISRT/DLET through         *
      * CALL 'CBLTDLI', and CHKP/XRST checkpoint-restart.              *
      *================================================================*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-FUNCTIONS.
           05  DLI-GU              PIC X(4) VALUE 'GU  '.
           05  DLI-GN              PIC X(4) VALUE 'GN  '.
           05  DLI-GNP             PIC X(4) VALUE 'GNP '.
           05  DLI-GHU             PIC X(4) VALUE 'GHU '.
           05  DLI-GHN             PIC X(4) VALUE 'GHN '.
           05  DLI-REPL            PIC X(4) VALUE 'REPL'.
           05  DLI-ISRT            PIC X(4) VALUE 'ISRT'.
           05  DLI-DLET            PIC X(4) VALUE 'DLET'.
           05  DLI-CHKP            PIC X(4) VALUE 'CHKP'.
           05  DLI-XRST            PIC X(4) VALUE 'XRST'.
       01  CUST-SSA-QUAL.
           05  FILLER              PIC X(8) VALUE 'CUSTSEG '.
           05  FILLER              PIC X VALUE '('.
           05  FILLER              PIC X(8) VALUE 'CUSTID  '.
           05  SSA-OPER            PIC XX VALUE ' ='.
           05  SSA-CUST-ID         PIC X(8).
           05  FILLER              PIC X VALUE ')'.
       01  CUST-SSA-UNQUAL.
           05  FILLER              PIC X(8) VALUE 'CUSTSEG '.
           05  FILLER              PIC X VALUE SPACE.
       01  ACCT-SSA-UNQUAL.
           05  FILLER              PIC X(8) VALUE 'ACCTSEG '.
           05  FILLER              PIC X VALUE SPACE.
       01  CUST-SEGMENT.
           05  CUST-ID             PIC X(8).
           05  CUST-NAME           PIC X(30).
           05  CUST-STATUS         PIC X.
       01  ACCT-SEGMENT.
           05  ACCT-NO             PIC X(10).
           05  ACCT-BALANCE        PIC S9(9)V99 COMP-3.
           05  ACCT-LAST-ACTIVITY  PIC 9(8).
       01  WS-CHKP-ID              PIC X(8) VALUE 'IMSDLIB1'.
       01  WS-CHKP-COUNT           PIC 9(5) COMP VALUE 0.
       01  WS-EOD                  PIC X VALUE 'N'.
           88  END-OF-DB           VALUE 'Y'.
       01  WS-PURGE-DATE           PIC 9(8) VALUE 20240101.
       LINKAGE SECTION.
       01  IO-PCB.
           05  IO-LTERM            PIC X(8).
           05  FILLER              PIC XX.
           05  IO-STATUS           PIC XX.
           05  IO-DATE             PIC S9(7) COMP-3.
           05  IO-TIME             PIC S9(7) COMP-3.
           05  IO-SEQ              PIC S9(5) COMP.
           05  IO-MOD-NAME         PIC X(8).
           05  IO-USERID           PIC X(8).
       01  CUST-PCB.
           05  CUST-DBD-NAME       PIC X(8).
           05  CUST-SEG-LEVEL      PIC XX.
           05  CUST-PCB-STATUS     PIC XX.
               88  DLI-OK          VALUE '  '.
               88  DLI-END         VALUE 'GB'.
               88  DLI-NOT-FOUND   VALUE 'GE'.
           05  CUST-PROC-OPT       PIC X(4).
           05  FILLER              PIC S9(5) COMP.
           05  CUST-SEG-NAME       PIC X(8).
           05  CUST-KEY-LEN        PIC S9(5) COMP.
           05  CUST-NUM-SENSEG     PIC S9(5) COMP.
           05  CUST-KEY-FB         PIC X(18).
       PROCEDURE DIVISION.
           ENTRY 'DLITCBL' USING IO-PCB CUST-PCB.
       0000-MAIN.
           CALL 'CBLTDLI' USING DLI-XRST IO-PCB WS-CHKP-ID
           PERFORM 1000-PROCESS-CUSTOMERS UNTIL END-OF-DB
           CALL 'CBLTDLI' USING DLI-CHKP IO-PCB WS-CHKP-ID
           GOBACK.
       1000-PROCESS-CUSTOMERS.
           CALL 'CBLTDLI' USING DLI-GN CUST-PCB CUST-SEGMENT
                                CUST-SSA-UNQUAL
           EVALUATE TRUE
               WHEN DLI-OK
                   PERFORM 2000-SCAN-ACCOUNTS
               WHEN DLI-END
                   SET END-OF-DB TO TRUE
               WHEN OTHER
                   DISPLAY 'GN CUSTSEG STATUS ' CUST-PCB-STATUS
                   SET END-OF-DB TO TRUE
           END-EVALUATE.
       2000-SCAN-ACCOUNTS.
           CALL 'CBLTDLI' USING DLI-GNP CUST-PCB ACCT-SEGMENT
                                ACCT-SSA-UNQUAL
           PERFORM UNTIL NOT DLI-OK
               IF ACCT-LAST-ACTIVITY < WS-PURGE-DATE
                   PERFORM 2100-DELETE-ACCOUNT
               ELSE
                   PERFORM 2200-FLAG-ACCOUNT
               END-IF
               CALL 'CBLTDLI' USING DLI-GNP CUST-PCB ACCT-SEGMENT
                                    ACCT-SSA-UNQUAL
           END-PERFORM
           ADD 1 TO WS-CHKP-COUNT
           IF WS-CHKP-COUNT > 500
               CALL 'CBLTDLI' USING DLI-CHKP IO-PCB WS-CHKP-ID
               MOVE 0 TO WS-CHKP-COUNT
           END-IF.
       2100-DELETE-ACCOUNT.
           CALL 'CBLTDLI' USING DLI-GHU CUST-PCB ACCT-SEGMENT
                                ACCT-SSA-UNQUAL
           IF DLI-OK
               CALL 'CBLTDLI' USING DLI-DLET CUST-PCB ACCT-SEGMENT
           END-IF.
       2200-FLAG-ACCOUNT.
           CALL 'CBLTDLI' USING DLI-GHN CUST-PCB ACCT-SEGMENT
                                ACCT-SSA-UNQUAL
           IF DLI-OK
               MOVE 'D' TO CUST-STATUS
               CALL 'CBLTDLI' USING DLI-REPL CUST-PCB ACCT-SEGMENT
               IF NOT DLI-OK
                   DISPLAY 'REPL FAILED ' CUST-PCB-STATUS
               END-IF
           END-IF.
