       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSMPP.
      *================================================================*
      * Program type: IMS message processing program (MPP / IFP).      *
      * Reads a transaction message off the I/O PCB, answers through   *
      * the I/O PCB and an alternate PCB (CHNG/ISRT/PURG), and uses    *
      * the express alternate PCB for the audit trail.                 *
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-FUNCTIONS.
           05  DLI-GU              PIC X(4) VALUE 'GU  '.
           05  DLI-GN              PIC X(4) VALUE 'GN  '.
           05  DLI-ISRT            PIC X(4) VALUE 'ISRT'.
           05  DLI-CHNG            PIC X(4) VALUE 'CHNG'.
           05  DLI-PURG            PIC X(4) VALUE 'PURG'.
       01  INPUT-MESSAGE.
           05  IN-LL               PIC S9(4) COMP.
           05  IN-ZZ               PIC S9(4) COMP.
           05  IN-TRANCODE         PIC X(8).
           05  IN-ACCT-NO          PIC X(10).
           05  IN-AMOUNT           PIC 9(7)V99.
           05  IN-ACTION           PIC X.
               88  IN-DEPOSIT      VALUE 'D'.
               88  IN-WITHDRAW     VALUE 'W'.
       01  OUTPUT-MESSAGE.
           05  OUT-LL              PIC S9(4) COMP VALUE 60.
           05  OUT-ZZ              PIC S9(4) COMP VALUE 0.
           05  OUT-TEXT            PIC X(56).
       01  AUDIT-MESSAGE.
           05  AUD-LL              PIC S9(4) COMP VALUE 40.
           05  AUD-ZZ              PIC S9(4) COMP VALUE 0.
           05  AUD-ACCT            PIC X(10).
           05  AUD-AMOUNT          PIC 9(7)V99.
           05  AUD-ACTION          PIC X.
           05  FILLER              PIC X(16).
       01  WS-ALT-DEST             PIC X(8) VALUE 'AUDITLT '.
       01  WS-MORE-MSGS            PIC X VALUE 'Y'.
           88  NO-MORE-MESSAGES    VALUE 'N'.
       01  ACCT-SSA.
           05  FILLER              PIC X(8) VALUE 'ACCTSEG '.
           05  FILLER              PIC X(9) VALUE '(ACCTNO ='.
           05  SSA-ACCT-NO         PIC X(10).
           05  FILLER              PIC X VALUE ')'.
       01  ACCT-SEGMENT.
           05  ACCT-NO             PIC X(10).
           05  ACCT-BALANCE        PIC S9(9)V99 COMP-3.
       LINKAGE SECTION.
       01  IO-PCB.
           05  IO-LTERM            PIC X(8).
           05  FILLER              PIC XX.
           05  IO-STATUS           PIC XX.
               88  IO-OK           VALUE '  '.
               88  IO-NO-MORE      VALUE 'QC'.
           05  FILLER              PIC X(20).
       01  ALT-PCB.
           05  ALT-DEST            PIC X(8).
           05  FILLER              PIC XX.
           05  ALT-STATUS          PIC XX.
       01  ACCT-PCB.
           05  ACCT-DBD-NAME       PIC X(8).
           05  ACCT-SEG-LEVEL      PIC XX.
           05  ACCT-STATUS         PIC XX.
               88  ACCT-OK         VALUE '  '.
           05  FILLER              PIC X(30).
       PROCEDURE DIVISION USING IO-PCB ALT-PCB ACCT-PCB.
       0000-MAIN.
           PERFORM UNTIL NO-MORE-MESSAGES
               CALL 'CBLTDLI' USING DLI-GU IO-PCB INPUT-MESSAGE
               EVALUATE TRUE
                   WHEN IO-OK
                       PERFORM 1000-PROCESS-MESSAGE
                   WHEN IO-NO-MORE
                       SET NO-MORE-MESSAGES TO TRUE
                   WHEN OTHER
                       DISPLAY 'IOPCB GU STATUS ' IO-STATUS
                       SET NO-MORE-MESSAGES TO TRUE
               END-EVALUATE
           END-PERFORM
           GOBACK.
       1000-PROCESS-MESSAGE.
           MOVE IN-ACCT-NO TO SSA-ACCT-NO
           CALL 'CBLTDLI' USING DLI-GU ACCT-PCB ACCT-SEGMENT ACCT-SSA
           IF NOT ACCT-OK
               MOVE 'ACCOUNT NOT FOUND' TO OUT-TEXT
           ELSE
               EVALUATE TRUE
                   WHEN IN-DEPOSIT
                       ADD IN-AMOUNT TO ACCT-BALANCE
                   WHEN IN-WITHDRAW
                       SUBTRACT IN-AMOUNT FROM ACCT-BALANCE
               END-EVALUATE
               CALL 'CBLTDLI' USING DLI-ISRT ACCT-PCB ACCT-SEGMENT
                                    ACCT-SSA
               MOVE 'POSTED' TO OUT-TEXT
               PERFORM 2000-AUDIT
           END-IF
           CALL 'CBLTDLI' USING DLI-ISRT IO-PCB OUTPUT-MESSAGE.
       2000-AUDIT.
           CALL 'CBLTDLI' USING DLI-CHNG ALT-PCB WS-ALT-DEST
           MOVE IN-ACCT-NO TO AUD-ACCT
           MOVE IN-AMOUNT TO AUD-AMOUNT
           MOVE IN-ACTION TO AUD-ACTION
           CALL 'CBLTDLI' USING DLI-ISRT ALT-PCB AUDIT-MESSAGE
           CALL 'CBLTDLI' USING DLI-PURG ALT-PCB.
