       IDENTIFICATION DIVISION.
       PROGRAM-ID. EODPROC.
      *****************************************************************
      * END-OF-DAY PROCESSING DRIVER PROGRAM                         *
      * DESCRIPTION: Orchestrates the bank's end-of-day batch cycle. *
      *   Runs daily cutoff procedures, produces GL summary totals,  *
      *   performs day-end account cutoff, generates batch control   *
      *   totals, and prepares for next business day processing.     *
      * CALLS:  GLRECON (COBOL) - GL reconciliation subroutine       *
      *         INTCALC (COBOL) - Interest calc subroutine           *
      *         DATEUTIL (ASM)  - Business day calculations          *
      *         CURRFMT (ASM)   - Currency formatting                *
      * DB2 PLAN: EODPLAN                                            *
      * FREQUENCY: Daily (after all batch jobs complete)             *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EODRPT ASSIGN TO EODRPT
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT EODCTRL ASSIGN TO EODCTRL
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  EODRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  EOD-RPT-RECORD            PIC X(133).

       FD  EODCTRL
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  EOD-CTRL-RECORD           PIC X(133).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

       COPY WSCOMMON.
       COPY ERRORCD.

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES - EOD SUMMARY QUERIES
      *-----------------------------------------------------------------
       01  WS-EOD-HV.
           05  HV-POST-DATE          PIC X(10).
           05  HV-TOTAL-DEPOSITS     PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-WITHDRAWALS  PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-TRANSFERS    PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-ACH-CREDITS  PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-ACH-DEBITS   PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-CHECKS       PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-INTEREST     PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-FEES         PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-LOAN-PMTS    PIC S9(17)V99 COMP-3.
           05  HV-TRAN-COUNT         PIC S9(9)       COMP.
           05  HV-ACCT-COUNT         PIC S9(9)       COMP.
           05  HV-TOTAL-ASSETS       PIC S9(17)V99 COMP-3.
           05  HV-TOTAL-LIABILITIES  PIC S9(17)V99 COMP-3.
           05  HV-NEXT-BUS-DATE      PIC X(10).

      *-----------------------------------------------------------------
      * DATE UTILITY PARMS
      *-----------------------------------------------------------------
       01  WS-DATE-PARMS.
           05  DP-FUNC               PIC X(01).
           05  DP-INDATE             PIC X(08).
           05  DP-INDATE2            PIC X(08).
           05  DP-OUTDATE            PIC X(08).
           05  DP-DAYSDIFF           PIC S9(9) COMP.
           05  DP-RETCODE            PIC X(01).

      *-----------------------------------------------------------------
      * CURRENCY FORMATTER PARMS
      *-----------------------------------------------------------------
       01  WS-CF-PARMS.
           05  CF-FUNCTION           PIC X(01).
           05  CF-AMOUNT             PIC S9(17)V99 COMP-3.
           05  CF-DR-CR              PIC X(01).
           05  CF-RESULT             PIC X(20).

      *-----------------------------------------------------------------
      * EOD CONTROL TOTALS
      *-----------------------------------------------------------------
       01  WS-EOD-TOTALS.
           05  WS-EOD-TOTAL-TRANS    PIC 9(11) COMP-3 VALUE ZERO.
           05  WS-EOD-TOTAL-CREDITS  PIC S9(17)V99 COMP-3 VALUE ZERO.
           05  WS-EOD-TOTAL-DEBITS   PIC S9(17)V99 COMP-3 VALUE ZERO.
           05  WS-EOD-NET-POSITION   PIC S9(17)V99 COMP-3 VALUE ZERO.
           05  WS-EOD-BALANCE-OK     PIC X(01) VALUE 'N'.
               88  WS-EOD-BALANCED   VALUE 'Y'.
               88  WS-EOD-OOB        VALUE 'N'.
           05  WS-EOD-COMPLETE-TS    PIC X(26).
           05  WS-EOD-NEXT-BUS-DATE  PIC X(10).

      *-----------------------------------------------------------------
      * REPORT LINES
      *-----------------------------------------------------------------
       01  WS-EOD-HDR.
           05  FILLER PIC X(50) VALUE
               'FIRST NATIONAL BANK - END OF DAY PROCESSING REPORT'.
           05  FILLER PIC X(20) VALUE '    BUSINESS DATE:  '.
           05  WS-EOD-HDR-DATE PIC X(10).
           05  FILLER PIC X(53) VALUE SPACES.

       01  WS-EOD-SEP.
           05  FILLER PIC X(133) VALUE ALL '='.

       01  WS-EOD-DETAIL-LINE.
           05  WS-EOD-LABEL          PIC X(40).
           05  WS-EOD-VALUE          PIC X(25).
           05  FILLER                PIC X(68) VALUE SPACES.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-EOD-TRANSACTION-SUMMARY
           PERFORM 3000-EOD-ACCOUNT-SUMMARY
           PERFORM 4000-EOD-GL-SUMMARY
           PERFORM 5000-SET-NEXT-BUSINESS-DATE
           PERFORM 6000-WRITE-EOD-CONTROL-RECORD
           PERFORM 7000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'EODPROC: END-OF-DAY PROCESSING STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE '-'
                  DELIMITED BY SIZE WS-CURRENT-MONTH
                  DELIMITED BY SIZE '-' DELIMITED BY SIZE
                  WS-CURRENT-DAY DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           MOVE WS-BUSINESS-DATE TO HV-POST-DATE
           MOVE WS-BUSINESS-DATE TO WS-EOD-HDR-DATE

           OPEN OUTPUT EODRPT
           OPEN OUTPUT EODCTRL

           WRITE EOD-RPT-RECORD FROM WS-EOD-HDR
           WRITE EOD-RPT-RECORD FROM WS-EOD-SEP.

       2000-EOD-TRANSACTION-SUMMARY.
           DISPLAY 'EODPROC: COMPUTING DAILY TRANSACTION TOTALS'

           EXEC SQL
               SELECT COUNT(*),
                      SUM(CASE WHEN TRAN_CODE='DEP '
                               THEN AMOUNT ELSE 0 END),
                      SUM(CASE WHEN TRAN_CODE='WDL '
                               THEN AMOUNT ELSE 0 END),
                      SUM(CASE WHEN TRAN_CODE IN ('XFI ','XFO')
                               THEN AMOUNT ELSE 0 END),
                      SUM(CASE WHEN TRAN_CODE='ACHC'
                               THEN AMOUNT ELSE 0 END),
                      SUM(CASE WHEN TRAN_CODE='ACHD'
                               THEN AMOUNT ELSE 0 END),
                      SUM(CASE WHEN TRAN_CODE='CHK '
                               THEN AMOUNT ELSE 0 END),
                      SUM(CASE WHEN TRAN_CODE='INT '
                               THEN AMOUNT ELSE 0 END),
                      SUM(CASE WHEN TRAN_CODE='FEE '
                               THEN AMOUNT ELSE 0 END),
                      SUM(CASE WHEN TRAN_CODE='LPM '
                               THEN AMOUNT ELSE 0 END)
               INTO   :HV-TRAN-COUNT,
                      :HV-TOTAL-DEPOSITS,
                      :HV-TOTAL-WITHDRAWALS,
                      :HV-TOTAL-TRANSFERS,
                      :HV-TOTAL-ACH-CREDITS,
                      :HV-TOTAL-ACH-DEBITS,
                      :HV-TOTAL-CHECKS,
                      :HV-TOTAL-INTEREST,
                      :HV-TOTAL-FEES,
                      :HV-TOTAL-LOAN-PMTS
               FROM   BANK.TRANSACTION_HIST
               WHERE  POST_DATE   = :HV-POST-DATE
               AND    TRAN_STATUS = 'P'
           END-EXEC

           IF SQLCODE NOT = 0
               DISPLAY 'EODPROC: TRANS SUMMARY ERROR SQLCODE=' SQLCODE
               ADD 1 TO WS-ERROR-COUNT
           ELSE
               PERFORM 2100-WRITE-TRANS-SUMMARY
           END-IF.

       2100-WRITE-TRANS-SUMMARY.
           MOVE 'TOTAL TRANSACTIONS:         ' TO WS-EOD-LABEL
           MOVE FUNCTION TRIM(HV-TRAN-COUNT) TO WS-EOD-VALUE
           WRITE EOD-RPT-RECORD FROM WS-EOD-DETAIL-LINE

           MOVE HV-TOTAL-DEPOSITS TO CF-AMOUNT
           MOVE 'F' TO CF-FUNCTION MOVE 'C' TO CF-DR-CR
           CALL 'CURRFMT' USING WS-CF-PARMS
           MOVE 'TOTAL DEPOSITS:             ' TO WS-EOD-LABEL
           MOVE CF-RESULT TO WS-EOD-VALUE
           WRITE EOD-RPT-RECORD FROM WS-EOD-DETAIL-LINE

           MOVE HV-TOTAL-WITHDRAWALS TO CF-AMOUNT
           CALL 'CURRFMT' USING WS-CF-PARMS
           MOVE 'TOTAL WITHDRAWALS:          ' TO WS-EOD-LABEL
           MOVE CF-RESULT TO WS-EOD-VALUE
           WRITE EOD-RPT-RECORD FROM WS-EOD-DETAIL-LINE

           MOVE HV-TOTAL-ACH-CREDITS TO CF-AMOUNT
           CALL 'CURRFMT' USING WS-CF-PARMS
           MOVE 'TOTAL ACH CREDITS:          ' TO WS-EOD-LABEL
           MOVE CF-RESULT TO WS-EOD-VALUE
           WRITE EOD-RPT-RECORD FROM WS-EOD-DETAIL-LINE

           MOVE HV-TOTAL-ACH-DEBITS TO CF-AMOUNT
           CALL 'CURRFMT' USING WS-CF-PARMS
           MOVE 'TOTAL ACH DEBITS:           ' TO WS-EOD-LABEL
           MOVE CF-RESULT TO WS-EOD-VALUE
           WRITE EOD-RPT-RECORD FROM WS-EOD-DETAIL-LINE

           MOVE HV-TOTAL-CHECKS TO CF-AMOUNT
           CALL 'CURRFMT' USING WS-CF-PARMS
           MOVE 'TOTAL CHECK CLEARINGS:      ' TO WS-EOD-LABEL
           MOVE CF-RESULT TO WS-EOD-VALUE
           WRITE EOD-RPT-RECORD FROM WS-EOD-DETAIL-LINE

           MOVE HV-TOTAL-INTEREST TO CF-AMOUNT
           CALL 'CURRFMT' USING WS-CF-PARMS
           MOVE 'TOTAL INTEREST PAID:        ' TO WS-EOD-LABEL
           MOVE CF-RESULT TO WS-EOD-VALUE
           WRITE EOD-RPT-RECORD FROM WS-EOD-DETAIL-LINE.

       3000-EOD-ACCOUNT-SUMMARY.
           EXEC SQL
               SELECT COUNT(*)
               INTO   :HV-ACCT-COUNT
               FROM   BANK.ACCOUNT
               WHERE  ACCT_STATUS = 'O'
           END-EXEC

           IF SQLCODE = 0
               MOVE 'TOTAL OPEN ACCOUNTS:        ' TO WS-EOD-LABEL
               MOVE FUNCTION TRIM(HV-ACCT-COUNT) TO WS-EOD-VALUE
               WRITE EOD-RPT-RECORD FROM WS-EOD-DETAIL-LINE
           END-IF.

       4000-EOD-GL-SUMMARY.
           EXEC SQL
               SELECT
                   SUM(CASE WHEN GL_ACCT_TYPE IN ('A')
                        THEN NET_BALANCE ELSE 0 END),
                   SUM(CASE WHEN GL_ACCT_TYPE IN ('L','E')
                        THEN NET_BALANCE ELSE 0 END)
               INTO   :HV-TOTAL-ASSETS,
                      :HV-TOTAL-LIABILITIES
               FROM   BANK.GL_ACCOUNT
               WHERE  GL_STATUS = 'A'
           END-EXEC

           IF SQLCODE = 0
               IF FUNCTION ABS(HV-TOTAL-ASSETS - HV-TOTAL-LIABILITIES)
                   < 0.01
                   SET WS-EOD-BALANCED TO TRUE
                   DISPLAY 'EODPROC: GL IS BALANCED'
               ELSE
                   SET WS-EOD-OOB TO TRUE
                   DISPLAY 'EODPROC: *** GL OUT OF BALANCE ***'
                   DISPLAY 'EODPROC: ASSETS     =' HV-TOTAL-ASSETS
                   DISPLAY 'EODPROC: LIABILITIES=' HV-TOTAL-LIABILITIES
                   ADD 1 TO WS-ERROR-COUNT
               END-IF
           END-IF.

       5000-SET-NEXT-BUSINESS-DATE.
      *    CALL ASSEMBLER DATE UTILITY TO GET NEXT BUSINESS DAY
           MOVE 'B' TO DP-FUNC
           MOVE WS-CURRENT-YEAR  TO DP-INDATE(1:4)
           MOVE WS-CURRENT-MONTH TO DP-INDATE(5:2)
           MOVE WS-CURRENT-DAY   TO DP-INDATE(7:2)
           CALL 'DATEUTIL' USING WS-DATE-PARMS
           MOVE DP-OUTDATE TO WS-EOD-NEXT-BUS-DATE
           DISPLAY 'EODPROC: NEXT BUSINESS DATE=' WS-EOD-NEXT-BUS-DATE.

       6000-WRITE-EOD-CONTROL-RECORD.
           MOVE WS-BUSINESS-DATE    TO WS-EOD-HDR-DATE
           MOVE FUNCTION CURRENT-DATE TO WS-EOD-COMPLETE-TS(1:21)
           WRITE EOD-RPT-RECORD FROM WS-EOD-SEP

           MOVE 'EOD COMPLETE' TO WS-EOD-LABEL
           MOVE WS-EOD-NEXT-BUS-DATE TO WS-EOD-VALUE
           WRITE EOD-CTRL-RECORD FROM WS-EOD-DETAIL-LINE.

       7000-FINALIZE.
           EXEC SQL COMMIT END-EXEC

           CLOSE EODRPT EODCTRL

           DISPLAY 'EODPROC: END-OF-DAY PROCESSING COMPLETE'
           DISPLAY 'BUSINESS DATE:       ' WS-BUSINESS-DATE
           DISPLAY 'NEXT BUSINESS DATE:  ' WS-EOD-NEXT-BUS-DATE
           DISPLAY 'GL BALANCED:         ' WS-EOD-BALANCE-OK
           DISPLAY 'ERRORS:              ' WS-ERROR-COUNT

           IF WS-EOD-OOB
               MOVE 8 TO RETURN-CODE
           ELSE IF WS-ERROR-COUNT > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
