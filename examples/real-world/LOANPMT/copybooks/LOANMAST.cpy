      *****************************************************************
      * LOAN MASTER RECORD LAYOUT                                   *
      * COPYBOOK: LOANMAST                                          *
      * DESCRIPTION: Loan account master record structure            *
      * USED BY: LOANPMT, INTCALC, STMTGEN, EODPROC               *
      *****************************************************************
       01  LOAN-MASTER-RECORD.
           05  LOAN-NUMBER               PIC X(12).
           05  LOAN-ACCT-NUMBER          PIC X(12).
           05  LOAN-CUST-ID             PIC X(10).
           05  LOAN-TYPE                 PIC X(04).
               88  LOAN-MORTGAGE         VALUE 'MORT'.
               88  LOAN-AUTO             VALUE 'AUTO'.
               88  LOAN-PERSONAL         VALUE 'PERS'.
               88  LOAN-HOME-EQUITY      VALUE 'HELC'.
               88  LOAN-LINE-OF-CREDIT   VALUE 'LOC '.
               88  LOAN-COMMERCIAL       VALUE 'COMM'.
           05  LOAN-STATUS               PIC X(01).
               88  LOAN-ACTIVE           VALUE 'A'.
               88  LOAN-PAID-OFF         VALUE 'P'.
               88  LOAN-DEFAULT          VALUE 'D'.
               88  LOAN-CHARGED-OFF      VALUE 'X'.
               88  LOAN-FORBEARANCE      VALUE 'F'.
           05  LOAN-ORIGINATION-DATE     PIC X(10).
           05  LOAN-MATURITY-DATE        PIC X(10).
           05  LOAN-ORIGINAL-AMOUNT      PIC S9(13)V99 COMP-3.
           05  LOAN-CURRENT-BALANCE      PIC S9(13)V99 COMP-3.
           05  LOAN-PRINCIPAL-PAID       PIC S9(13)V99 COMP-3.
           05  LOAN-INTEREST-RATE        PIC 9(03)V9(6).
           05  LOAN-RATE-TYPE            PIC X(01).
               88  LOAN-FIXED-RATE       VALUE 'F'.
               88  LOAN-VARIABLE-RATE    VALUE 'V'.
           05  LOAN-TERM-MONTHS          PIC 9(04).
           05  LOAN-PAYMENT-AMOUNT       PIC S9(09)V99 COMP-3.
           05  LOAN-NEXT-DUE-DATE        PIC X(10).
           05  LOAN-LAST-PMT-DATE        PIC X(10).
           05  LOAN-LAST-PMT-AMOUNT      PIC S9(09)V99 COMP-3.
           05  LOAN-DAYS-PAST-DUE        PIC 9(04).
           05  LOAN-LATE-FEE-AMOUNT      PIC S9(07)V99 COMP-3.
           05  LOAN-LATE-FEE-ASSESSED    PIC X(01).
               88  LOAN-LATE-FEE-YES     VALUE 'Y'.
               88  LOAN-LATE-FEE-NO      VALUE 'N'.
           05  LOAN-ESCROW-BALANCE       PIC S9(09)V99 COMP-3.
           05  LOAN-ESCROW-PAYMENT       PIC S9(07)V99 COMP-3.
           05  LOAN-INTEREST-ACCRUED     PIC S9(09)V99 COMP-3.
           05  LOAN-INTEREST-YTD         PIC S9(11)V99 COMP-3.
           05  LOAN-OFFICER-CODE         PIC X(05).
           05  LOAN-COLLATERAL-CODE      PIC X(04).
           05  LOAN-LAST-UPDATE-TS       PIC X(26).
           05  FILLER                    PIC X(15).
