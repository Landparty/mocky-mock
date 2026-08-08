       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOANPMT.
      *****************************************************************
      * LOAN PAYMENT PROCESSING PROGRAM                              *
      * DESCRIPTION: Processes scheduled loan payments, applies      *
      *   payments to principal and interest, assesses late fees,    *
      *   updates amortization schedule, and posts GL entries.       *
      * INPUT:  DB2 BANK.LOAN (active loans due today/past due)      *
      *         IMS LOANDB    (loan customer segments)               *
      * OUTPUT: DB2 BANK.LOAN updated balance, dates, status         *
      *         DB2 BANK.TRANSACTION_HIST payment postings           *
      *         LOANRPT - Loan payment activity report               *
      * CALLS:  INTRATE  (Assembler) - daily interest computation    *
      *         CBLTDLI  (IMS DL/I)  - customer segment access       *
      * DB2 PLAN: LOANPLAN                                           *
      * IMS PSB: LOANPSB                                             *
      * FREQUENCY: Daily (runs during EOD cycle)                     *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOANRPT ASSIGN TO LOANRPT
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT PMTFILE ASSIGN TO PMTFILE
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-PMT-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  LOANRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD                PIC X(133).

       FD  PMTFILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  PMT-RECORD.
           05  PMT-LOAN-NUMBER       PIC X(12).
           05  PMT-AMOUNT            PIC S9(9)V99 COMP-3.
           05  PMT-DATE              PIC X(10).
           05  PMT-TYPE              PIC X(02).
               88  PMT-REGULAR       VALUE 'RM'.
               88  PMT-EXTRA-PRIN    VALUE 'EP'.
               88  PMT-PAYOFF        VALUE 'PO'.
           05  FILLER                PIC X(51).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

       COPY WSCOMMON.
       COPY ERRORCD.
       COPY LOANMAST.
       COPY IMSPCB.

       01  WS-PMT-STATUS             PIC X(02).
           88  WS-PMT-OK             VALUE '00'.
           88  WS-PMT-EOF            VALUE '10'.

       01  WS-FATAL-ERROR-FLAG       PIC X(01) VALUE 'N'.
           88  FATAL-ERROR-FOUND     VALUE 'Y'.

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES
      *-----------------------------------------------------------------
       01  WS-LOAN-HV.
           05  HV-LOAN-NUMBER        PIC X(12).
           05  HV-ACCT-NUMBER        PIC X(12).
           05  HV-CIF-NUMBER         PIC X(10).
           05  HV-LOAN-TYPE          PIC X(04).
           05  HV-LOAN-STATUS        PIC X(01).
           05  HV-CURRENT-BALANCE    PIC S9(13)V99  COMP-3.
           05  HV-INTEREST-RATE      PIC S9(3)V9(6) COMP-3.
           05  HV-PAYMENT-AMOUNT     PIC S9(9)V99   COMP-3.
           05  HV-NEXT-DUE-DATE      PIC X(10).
           05  HV-LAST-PMT-DATE      PIC X(10).
           05  HV-DAYS-PAST-DUE      PIC S9(4)       COMP.
           05  HV-LATE-FEE           PIC S9(7)V99   COMP-3.
           05  HV-LATE-FEE-ASSESSED  PIC X(01).
           05  HV-ESCROW-PMT         PIC S9(7)V99   COMP-3.
           05  HV-INTEREST-ACCRUED   PIC S9(9)V99   COMP-3.
           05  HV-PRINCIPAL-PAID     PIC S9(13)V99  COMP-3.
           05  HV-INT-YTD            PIC S9(13)V99  COMP-3.
           05  HV-TRAN-ID            PIC X(16).
           05  HV-TRAN-AMOUNT        PIC S9(13)V99  COMP-3.
           05  HV-PRINCIPAL-PORTION  PIC S9(11)V99  COMP-3.
           05  HV-INTEREST-PORTION   PIC S9(11)V99  COMP-3.

      *-----------------------------------------------------------------
      * LOAN CURSOR - ACTIVE LOANS DUE TODAY OR PAST DUE
      *-----------------------------------------------------------------
           EXEC SQL
               DECLARE LOAN_CURSOR CURSOR FOR
               SELECT L.LOAN_NUMBER,
                      L.ACCT_NUMBER,
                      L.CIF_NUMBER,
                      L.LOAN_TYPE,
                      L.LOAN_STATUS,
                      L.CURRENT_BALANCE,
                      L.INTEREST_RATE,
                      L.PAYMENT_AMOUNT,
                      L.NEXT_DUE_DATE,
                      L.LAST_PMT_DATE,
                      L.DAYS_PAST_DUE,
                      L.LATE_FEE_AMOUNT,
                      L.LATE_FEE_ASSESSED,
                      L.ESCROW_PAYMENT,
                      L.INTEREST_ACCRUED,
                      L.PRINCIPAL_PAID,
                      L.INTEREST_YTD
               FROM   BANK.LOAN L
               WHERE  L.LOAN_STATUS = 'A'
               AND    L.NEXT_DUE_DATE <= CURRENT DATE
               FOR    UPDATE OF CURRENT_BALANCE,
                                PRINCIPAL_PAID,
                                DAYS_PAST_DUE,
                                LATE_FEE_AMOUNT,
                                LATE_FEE_ASSESSED,
                                LAST_PMT_DATE,
                                NEXT_DUE_DATE,
                                INTEREST_ACCRUED,
                                INTEREST_YTD,
                                LAST_UPDATE_TS,
                                LAST_UPDATE_USER
           END-EXEC.

      *-----------------------------------------------------------------
      * ASSEMBLER INTEREST RATE PARMS
      *-----------------------------------------------------------------
       01  WS-INT-PARMS.
           05  IP-FUNC               PIC X(01) VALUE 'D'.
           05  IP-ACCT-TYPE          PIC X(01) VALUE 'L'.
           05  IP-BALANCE            PIC S9(13)V99 COMP-3.
           05  IP-ANNUAL-RATE        PIC S9(3)V9(6) COMP-3.
           05  IP-CALC-DAYS          PIC S9(4)      COMP-3.
           05  IP-INTEREST-AMT       PIC S9(13)V99 COMP-3.
           05  IP-RETURN-CODE        PIC X(02).

      *-----------------------------------------------------------------
      * AMORTIZATION WORK AREAS
      *-----------------------------------------------------------------
       01  WS-AMORT.
           05  WS-MONTHLY-INTEREST   PIC S9(11)V99 COMP-3.
           05  WS-PRINCIPAL-PORTION  PIC S9(11)V99 COMP-3.
           05  WS-INTEREST-PORTION   PIC S9(11)V99 COMP-3.
           05  WS-LATE-FEE-AMOUNT    PIC S9(07)V99 COMP-3 VALUE 25.00.

       01  WS-DAYS-WORK              PIC S9(9)     COMP.
       01  WS-ASM-RC                 PIC S9(4)     COMP.
       01  WS-TRAN-SEED              PIC 9(16)     COMP VALUE ZERO.

      *-----------------------------------------------------------------
      * IMS CALL PARAMETERS
      *-----------------------------------------------------------------
       01  WS-IMS-CUST-AREA          PIC X(300).
       01  WS-IMS-RC                 PIC S9(4)     COMP.

      *-----------------------------------------------------------------
      * REPORT LINE
      *-----------------------------------------------------------------
       01  WS-HDR.
           05  FILLER PIC X(13) VALUE 'LOAN NUMBER  '.
           05  FILLER PIC X(05) VALUE 'TYPE '.
           05  FILLER PIC X(17) VALUE '   PAYMENT AMOUNT'.
           05  FILLER PIC X(17) VALUE '     PRINCIPAL   '.
           05  FILLER PIC X(17) VALUE '     INTEREST    '.
           05  FILLER PIC X(17) VALUE '   NEW BALANCE   '.
           05  FILLER PIC X(08) VALUE 'DPD     '.

       01  WS-DETAIL.
           05  WS-DET-LOAN          PIC X(12).
           05  FILLER               PIC X(01) VALUE SPACE.
           05  WS-DET-TYPE          PIC X(04).
           05  FILLER               PIC X(01) VALUE SPACE.
           05  WS-DET-PAYMENT       PIC ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-PRINCIPAL     PIC ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-INTEREST      PIC ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-NEW-BAL       PIC ZZZ,ZZZ,ZZZ,ZZ9.99.
           05  FILLER               PIC X(02) VALUE SPACES.
           05  WS-DET-DPD           PIC ZZ9.

      *-----------------------------------------------------------------
      * COUNTERS
      *-----------------------------------------------------------------
       01  WS-LOAN-CNTS.
           05  WS-LOANS-PROCESSED   PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-PMTS-APPLIED      PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-LATE-FEES         PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-LOANS-DEFAULT     PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-TOTAL-PMT-AMT     PIC S9(15)V99 COMP-3 VALUE ZERO.
           05  WS-TOTAL-PRINCIPAL   PIC S9(15)V99 COMP-3 VALUE ZERO.
           05  WS-TOTAL-INTEREST    PIC S9(15)V99 COMP-3 VALUE ZERO.
           05  WS-LOAN-ERRORS       PIC 9(05) COMP-3 VALUE ZERO.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS-LOANS
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'LOANPMT: LOAN PAYMENT PROCESSING STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE '-'
                  DELIMITED BY SIZE WS-CURRENT-MONTH
                  DELIMITED BY SIZE '-' DELIMITED BY SIZE
                  WS-CURRENT-DAY DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           OPEN INPUT  PMTFILE
           OPEN OUTPUT LOANRPT
           WRITE RPT-RECORD FROM WS-HDR

           EXEC SQL OPEN LOAN_CURSOR END-EXEC
           IF SQLCODE NOT = 0
               DISPLAY 'LOANPMT: CANNOT OPEN LOAN_CURSOR SQLCODE='
                       SQLCODE
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.

       2000-PROCESS-LOANS.
           PERFORM 2100-FETCH-LOAN
               UNTIL SQLCODE = +100 OR FATAL-ERROR-FOUND.

       2100-FETCH-LOAN.
           EXEC SQL
               FETCH LOAN_CURSOR
               INTO  :HV-LOAN-NUMBER,
                     :HV-ACCT-NUMBER,
                     :HV-CIF-NUMBER,
                     :HV-LOAN-TYPE,
                     :HV-LOAN-STATUS,
                     :HV-CURRENT-BALANCE,
                     :HV-INTEREST-RATE,
                     :HV-PAYMENT-AMOUNT,
                     :HV-NEXT-DUE-DATE,
                     :HV-LAST-PMT-DATE,
                     :HV-DAYS-PAST-DUE,
                     :HV-LATE-FEE,
                     :HV-LATE-FEE-ASSESSED,
                     :HV-ESCROW-PMT,
                     :HV-INTEREST-ACCRUED,
                     :HV-PRINCIPAL-PAID,
                     :HV-INT-YTD
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   ADD 1 TO WS-LOANS-PROCESSED
                   PERFORM 2200-CALC-INTEREST-PORTION
                   PERFORM 2300-APPLY-PAYMENT
                   PERFORM 2400-CHECK-LATE-FEE
                   PERFORM 2500-UPDATE-LOAN-RECORD
               WHEN +100
                   CONTINUE
               WHEN OTHER
                   DISPLAY 'LOANPMT: FETCH ERROR SQLCODE=' SQLCODE
                   SET FATAL-ERROR-FOUND TO TRUE
           END-EVALUATE.

       2200-CALC-INTEREST-PORTION.
      *    CALL ASSEMBLER TO COMPUTE DAYS INTEREST (30/360 CONVENTION)
           MOVE 'D' TO IP-FUNC
           MOVE 'L' TO IP-ACCT-TYPE
           MOVE HV-CURRENT-BALANCE TO IP-BALANCE
           MOVE HV-INTEREST-RATE   TO IP-ANNUAL-RATE
           MOVE 30                 TO IP-CALC-DAYS

           CALL 'INTRATE' USING WS-INT-PARMS
           MOVE RETURN-CODE TO WS-ASM-RC

           IF WS-ASM-RC NOT = ZERO
               DISPLAY 'LOANPMT: INTRATE ERROR LOAN=' HV-LOAN-NUMBER
                       ' RC=' WS-ASM-RC
               ADD 1 TO WS-LOAN-ERRORS
               MOVE ZERO TO WS-INTEREST-PORTION
               MOVE HV-PAYMENT-AMOUNT TO WS-PRINCIPAL-PORTION
           ELSE
               MOVE IP-INTEREST-AMT TO WS-INTEREST-PORTION
               SUBTRACT WS-INTEREST-PORTION FROM HV-PAYMENT-AMOUNT
                   GIVING WS-PRINCIPAL-PORTION
           END-IF.

       2300-APPLY-PAYMENT.
      *    CALL IMS TO RETRIEVE CUSTOMER SEGMENT FOR AUDIT
           MOVE HV-CIF-NUMBER TO SSA-CUST-KEY-VALUE
           CALL 'CBLTDLI' USING DLI-GU
                                CUSTOMER-PCB-MASK
                                WS-IMS-CUST-AREA
                                SSA-CUSTOMER

           MOVE WS-INTEREST-PORTION TO HV-INTEREST-PORTION
           MOVE WS-PRINCIPAL-PORTION TO HV-PRINCIPAL-PORTION

           SUBTRACT WS-PRINCIPAL-PORTION FROM HV-CURRENT-BALANCE
           ADD WS-PRINCIPAL-PORTION TO HV-PRINCIPAL-PAID
           ADD WS-INTEREST-PORTION  TO HV-INT-YTD
           ADD 1 TO WS-PMTS-APPLIED
           ADD HV-PAYMENT-AMOUNT TO WS-TOTAL-PMT-AMT
           ADD WS-PRINCIPAL-PORTION TO WS-TOTAL-PRINCIPAL
           ADD WS-INTEREST-PORTION TO WS-TOTAL-INTEREST

      *    POST PAYMENT TRANSACTION
           ADD 1 TO WS-TRAN-SEED
           MOVE WS-TRAN-SEED TO HV-TRAN-ID
           MOVE HV-PAYMENT-AMOUNT TO HV-TRAN-AMOUNT
           EXEC SQL
               INSERT INTO BANK.TRANSACTION_HIST
                      (TRAN_ID, ACCT_NUMBER, TRAN_TYPE, TRAN_CODE,
                       AMOUNT, EFFECTIVE_DATE, POST_DATE,
                       DESCRIPTION, CHANNEL, TRAN_STATUS)
               VALUES (:HV-TRAN-ID, :HV-ACCT-NUMBER, 'DR', 'LPM ',
                       :HV-TRAN-AMOUNT, :WS-BUSINESS-DATE,
                       :WS-BUSINESS-DATE,
                       'LOAN PAYMENT', 'BAT', 'P')
           END-EXEC

           MOVE WS-BUSINESS-DATE TO HV-LAST-PMT-DATE
           MOVE ZERO TO HV-DAYS-PAST-DUE.

       2400-CHECK-LATE-FEE.
      *    ASSESS LATE FEE IF > 15 DAYS PAST DUE AND NOT YET CHARGED
           IF HV-DAYS-PAST-DUE > 15
           AND HV-LATE-FEE-ASSESSED = 'N'
               ADD WS-LATE-FEE-AMOUNT TO HV-CURRENT-BALANCE
               MOVE 'Y' TO HV-LATE-FEE-ASSESSED
               MOVE WS-LATE-FEE-AMOUNT TO HV-LATE-FEE
               ADD 1 TO WS-LATE-FEES
               ADD 1 TO WS-TRAN-SEED
               MOVE WS-TRAN-SEED TO HV-TRAN-ID
               MOVE WS-LATE-FEE-AMOUNT TO HV-TRAN-AMOUNT
               EXEC SQL
                   INSERT INTO BANK.TRANSACTION_HIST
                          (TRAN_ID, ACCT_NUMBER, TRAN_TYPE, TRAN_CODE,
                           AMOUNT, EFFECTIVE_DATE, POST_DATE,
                           DESCRIPTION, CHANNEL, TRAN_STATUS)
                   VALUES (:HV-TRAN-ID, :HV-ACCT-NUMBER, 'DR', 'FEE ',
                           :HV-TRAN-AMOUNT, :WS-BUSINESS-DATE,
                           :WS-BUSINESS-DATE,
                           'LATE PAYMENT FEE', 'BAT', 'P')
               END-EXEC
           END-IF.

       2500-UPDATE-LOAN-RECORD.
           EXEC SQL
               UPDATE BANK.LOAN
               SET    CURRENT_BALANCE    = :HV-CURRENT-BALANCE,
                      PRINCIPAL_PAID     = :HV-PRINCIPAL-PAID,
                      DAYS_PAST_DUE      = :HV-DAYS-PAST-DUE,
                      LATE_FEE_AMOUNT    = :HV-LATE-FEE,
                      LATE_FEE_ASSESSED  = :HV-LATE-FEE-ASSESSED,
                      LAST_PMT_DATE      = :HV-LAST-PMT-DATE,
                      INTEREST_YTD       = :HV-INT-YTD,
                      LAST_UPDATE_TS     = CURRENT TIMESTAMP,
                      LAST_UPDATE_USER   = 'LOANPMT'
               WHERE  CURRENT OF LOAN_CURSOR
           END-EXEC

           IF SQLCODE NOT = 0
               DISPLAY 'LOANPMT: UPDATE ERROR LOAN=' HV-LOAN-NUMBER
                       ' SQLCODE=' SQLCODE
               ADD 1 TO WS-LOAN-ERRORS
               EXEC SQL ROLLBACK END-EXEC
           ELSE
               ADD 1 TO WS-COMMIT-COUNT
               IF WS-COMMIT-COUNT >= WS-COMMIT-FREQ
                   EXEC SQL COMMIT END-EXEC
                   MOVE ZERO TO WS-COMMIT-COUNT
               END-IF
           END-IF

           MOVE HV-LOAN-NUMBER      TO WS-DET-LOAN
           MOVE HV-LOAN-TYPE        TO WS-DET-TYPE
           MOVE HV-PAYMENT-AMOUNT   TO WS-DET-PAYMENT
           MOVE WS-PRINCIPAL-PORTION TO WS-DET-PRINCIPAL
           MOVE WS-INTEREST-PORTION  TO WS-DET-INTEREST
           MOVE HV-CURRENT-BALANCE   TO WS-DET-NEW-BAL
           MOVE HV-DAYS-PAST-DUE     TO WS-DET-DPD
           WRITE RPT-RECORD FROM WS-DETAIL.

       3000-FINALIZE.
           EXEC SQL COMMIT END-EXEC
           EXEC SQL CLOSE LOAN_CURSOR END-EXEC

           CLOSE PMTFILE
           CLOSE LOANRPT

           DISPLAY 'LOANPMT: LOAN PAYMENT PROCESSING COMPLETE'
           DISPLAY 'LOANS PROCESSED:     ' WS-LOANS-PROCESSED
           DISPLAY 'PAYMENTS APPLIED:    ' WS-PMTS-APPLIED
           DISPLAY 'LATE FEES ASSESSED:  ' WS-LATE-FEES
           DISPLAY 'TOTAL PMT AMOUNT:    ' WS-TOTAL-PMT-AMT
           DISPLAY 'TOTAL PRINCIPAL:     ' WS-TOTAL-PRINCIPAL
           DISPLAY 'TOTAL INTEREST:      ' WS-TOTAL-INTEREST
           DISPLAY 'ERRORS:              ' WS-LOAN-ERRORS

           IF WS-LOAN-ERRORS > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
