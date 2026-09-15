       IDENTIFICATION DIVISION.
       PROGRAM-ID. BATCHSEQ.
       AUTHOR. ENTERPRISE COVERAGE CORPUS.
      *================================================================*
      * Program type: classic QSAM batch job step.                     *
      * Reads a sequential transaction file, sorts it with an INPUT    *
      * PROCEDURE / OUTPUT PROCEDURE pair, writes a control report,    *
      * and takes checkpoints through I-O-CONTROL RERUN.               *
      *================================================================*
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-390.
       OBJECT-COMPUTER. IBM-390.
       SPECIAL-NAMES.
           SYSOUT IS SYSPRINT
           C01 IS TOP-OF-PAGE.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRAN-FILE ASSIGN TO TRANIN
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-TRAN-STATUS.
           SELECT SORT-WORK ASSIGN TO SORTWK01.
           SELECT REPORT-FILE ASSIGN TO RPTOUT
               FILE STATUS IS WS-RPT-STATUS.
           SELECT CHKPT-FILE ASSIGN TO CHKPTOUT
               FILE STATUS IS WS-CHK-STATUS.
       I-O-CONTROL.
           RERUN ON CHKPT-FILE EVERY 1000 RECORDS OF TRAN-FILE
           SAME RECORD AREA FOR TRAN-FILE REPORT-FILE
           APPLY WRITE-ONLY ON REPORT-FILE.
       DATA DIVISION.
       FILE SECTION.
       FD  TRAN-FILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS
           RECORD CONTAINS 80 CHARACTERS
           LABEL RECORDS ARE STANDARD
           DATA RECORD IS TRAN-REC.
       01  TRAN-REC.
           05  TRAN-ACCT           PIC X(10).
           05  TRAN-TYPE           PIC X.
               88  TRAN-DEBIT      VALUE 'D'.
               88  TRAN-CREDIT     VALUE 'C'.
           05  TRAN-AMOUNT         PIC S9(9)V99 COMP-3.
           05  TRAN-DATE           PIC 9(8).
           05  FILLER              PIC X(55).
       SD  SORT-WORK
           RECORD CONTAINS 80 CHARACTERS.
       01  SORT-REC.
           05  SORT-ACCT           PIC X(10).
           05  SORT-TYPE           PIC X.
           05  SORT-AMOUNT         PIC S9(9)V99 COMP-3.
           05  SORT-DATE           PIC 9(8).
           05  FILLER              PIC X(55).
       FD  REPORT-FILE
           RECORDING MODE IS F
           RECORD CONTAINS 133 CHARACTERS.
       01  REPORT-REC              PIC X(133).
       FD  CHKPT-FILE
           RECORDING MODE IS F
           RECORD CONTAINS 80 CHARACTERS.
       01  CHKPT-REC               PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-STATUS-AREA.
           05  WS-TRAN-STATUS      PIC XX.
               88  TRAN-OK         VALUE '00'.
               88  TRAN-EOF        VALUE '10'.
           05  WS-RPT-STATUS       PIC XX.
           05  WS-CHK-STATUS       PIC XX.
       01  WS-COUNTERS.
           05  WS-READ-COUNT       PIC 9(7) COMP VALUE 0.
           05  WS-WRITTEN-COUNT    PIC 9(7) COMP VALUE 0.
           05  WS-DEBIT-TOTAL      PIC S9(11)V99 COMP-3 VALUE 0.
           05  WS-CREDIT-TOTAL     PIC S9(11)V99 COMP-3 VALUE 0.
       01  WS-RUN-DATE.
           05  WS-RUN-YYYY         PIC 9(4).
           05  WS-RUN-MM           PIC 99.
           05  WS-RUN-DD           PIC 99.
       01  WS-DAY-OF-WEEK          PIC 9.
       01  WS-EOF-FLAG             PIC X VALUE 'N'.
           88  END-OF-TRANS        VALUE 'Y'.
       01  WS-PRINT-LINE.
           05  FILLER              PIC X VALUE SPACE.
           05  PL-ACCT             PIC X(10).
           05  FILLER              PIC X(3) VALUE SPACES.
           05  PL-TYPE             PIC X.
           05  FILLER              PIC X(3) VALUE SPACES.
           05  PL-AMOUNT           PIC Z(8)9.99-.
           05  FILLER              PIC X(102) VALUE SPACES.
       01  WS-HEADER-LINE.
           05  FILLER              PIC X(19) VALUE 'DAILY TRANSACTIONS'.
           05  HL-DATE             PIC 9999/99/99.
           05  FILLER              PIC X(103) VALUE SPACES.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           SORT SORT-WORK
               ON ASCENDING KEY SORT-ACCT
               ON DESCENDING KEY SORT-DATE
               INPUT PROCEDURE IS 2000-SELECT-INPUT
               OUTPUT PROCEDURE IS 3000-WRITE-REPORT
           PERFORM 9000-FINISH
           STOP RUN.
       1000-INIT.
           ACCEPT WS-RUN-DATE FROM DATE YYYYMMDD
           ACCEPT WS-DAY-OF-WEEK FROM DAY-OF-WEEK
           OPEN INPUT TRAN-FILE
                OUTPUT REPORT-FILE CHKPT-FILE
           IF NOT TRAN-OK
               DISPLAY 'TRANIN OPEN FAILED ' WS-TRAN-STATUS
                   UPON SYSPRINT
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF
           MOVE WS-RUN-DATE TO HL-DATE
           WRITE REPORT-REC FROM WS-HEADER-LINE AFTER ADVANCING PAGE.
       2000-SELECT-INPUT.
           PERFORM UNTIL END-OF-TRANS
               READ TRAN-FILE
                   AT END SET END-OF-TRANS TO TRUE
                   NOT AT END
                       ADD 1 TO WS-READ-COUNT
                       IF TRAN-DEBIT OR TRAN-CREDIT
                           MOVE TRAN-REC TO SORT-REC
                           RELEASE SORT-REC
                       END-IF
               END-READ
           END-PERFORM.
       3000-WRITE-REPORT.
           PERFORM UNTIL WS-EOF-FLAG = 'E'
               RETURN SORT-WORK
                   AT END MOVE 'E' TO WS-EOF-FLAG
                   NOT AT END PERFORM 3100-PRINT-LINE
               END-RETURN
           END-PERFORM.
       3100-PRINT-LINE.
           MOVE SORT-ACCT TO PL-ACCT
           MOVE SORT-TYPE TO PL-TYPE
           MOVE SORT-AMOUNT TO PL-AMOUNT
           EVALUATE SORT-TYPE
               WHEN 'D' ADD SORT-AMOUNT TO WS-DEBIT-TOTAL
               WHEN 'C' ADD SORT-AMOUNT TO WS-CREDIT-TOTAL
           END-EVALUATE
           WRITE REPORT-REC FROM WS-PRINT-LINE AFTER ADVANCING 1 LINE
           ADD 1 TO WS-WRITTEN-COUNT.
       9000-FINISH.
           CLOSE TRAN-FILE REPORT-FILE CHKPT-FILE
           DISPLAY 'READ=' WS-READ-COUNT ' WRITTEN=' WS-WRITTEN-COUNT
               UPON SYSPRINT
           MOVE 0 TO RETURN-CODE.
