      *****************************************************************
      * ACCOUNT MASTER RECORD LAYOUT                                 *
      * COPYBOOK: ACCTMAST                                           *
      * DESCRIPTION: Bank account master file record structure       *
      * USED BY: ACCTMNT, INTCALC, STMTGEN, CHKCLR, DORMACCT,     *
      *          EODPROC, GLRECON                                    *
      *****************************************************************
       01  ACCOUNT-MASTER-RECORD.
           05  ACCT-NUMBER                PIC X(12).
           05  ACCT-TYPE                  PIC X(03).
               88  ACCT-CHECKING          VALUE 'CHK'.
               88  ACCT-SAVINGS           VALUE 'SAV'.
               88  ACCT-MONEY-MARKET      VALUE 'MMA'.
               88  ACCT-CERT-DEPOSIT      VALUE 'CDA'.
               88  ACCT-IRA               VALUE 'IRA'.
           05  ACCT-STATUS                PIC X(01).
               88  ACCT-OPEN              VALUE 'O'.
               88  ACCT-CLOSED            VALUE 'C'.
               88  ACCT-FROZEN            VALUE 'F'.
               88  ACCT-DORMANT           VALUE 'D'.
               88  ACCT-ESCHEAT           VALUE 'E'.
           05  ACCT-CUST-ID              PIC X(10).
           05  ACCT-BRANCH-CODE          PIC X(04).
           05  ACCT-OPEN-DATE            PIC X(10).
           05  ACCT-CLOSE-DATE           PIC X(10).
           05  ACCT-LAST-ACTIVITY-DATE   PIC X(10).
           05  ACCT-CURRENT-BALANCE      PIC S9(13)V99 COMP-3.
           05  ACCT-AVAILABLE-BALANCE    PIC S9(13)V99 COMP-3.
           05  ACCT-HOLD-AMOUNT          PIC S9(11)V99 COMP-3.
           05  ACCT-INTEREST-RATE        PIC 9(03)V9(6).
           05  ACCT-INTEREST-ACCRUED     PIC S9(11)V99 COMP-3.
           05  ACCT-INTEREST-YTD         PIC S9(11)V99 COMP-3.
           05  ACCT-INTEREST-LAST-PAID   PIC X(10).
           05  ACCT-OVERDRAFT-LIMIT      PIC S9(09)V99 COMP-3.
           05  ACCT-MIN-BALANCE          PIC S9(09)V99 COMP-3.
           05  ACCT-MONTHLY-FEE          PIC S9(05)V99 COMP-3.
           05  ACCT-STMT-CYCLE           PIC X(02).
               88  ACCT-CYCLE-MONTHLY    VALUE '01' THRU '28'.
           05  ACCT-LAST-STMT-DATE       PIC X(10).
           05  ACCT-CD-MATURITY-DATE     PIC X(10).
           05  ACCT-CD-TERM-MONTHS       PIC 9(03).
           05  ACCT-OFFICER-CODE         PIC X(05).
           05  ACCT-LAST-UPDATE-TS       PIC X(26).
           05  ACCT-LAST-UPDATE-USER     PIC X(08).
           05  FILLER                    PIC X(20).
