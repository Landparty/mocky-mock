      *****************************************************************
      * GENERAL LEDGER ACCOUNT RECORD LAYOUT                        *
      * COPYBOOK: GLACCT                                             *
      * DESCRIPTION: GL account structure for financial reporting    *
      * USED BY: GLRECON, EODPROC                                   *
      *****************************************************************
       01  GL-ACCOUNT-RECORD.
           05  GL-ACCOUNT-NUMBER         PIC X(10).
           05  GL-ACCOUNT-NAME           PIC X(40).
           05  GL-ACCOUNT-TYPE           PIC X(01).
               88  GL-ASSET              VALUE 'A'.
               88  GL-LIABILITY          VALUE 'L'.
               88  GL-EQUITY             VALUE 'E'.
               88  GL-REVENUE            VALUE 'R'.
               88  GL-EXPENSE            VALUE 'X'.
           05  GL-DEPARTMENT-CODE        PIC X(04).
           05  GL-COST-CENTER            PIC X(06).
           05  GL-DEBIT-BALANCE          PIC S9(15)V99 COMP-3.
           05  GL-CREDIT-BALANCE         PIC S9(15)V99 COMP-3.
           05  GL-NET-BALANCE            PIC S9(15)V99 COMP-3.
           05  GL-PRIOR-DAY-BALANCE      PIC S9(15)V99 COMP-3.
           05  GL-MTD-DEBITS             PIC S9(15)V99 COMP-3.
           05  GL-MTD-CREDITS            PIC S9(15)V99 COMP-3.
           05  GL-YTD-DEBITS             PIC S9(15)V99 COMP-3.
           05  GL-YTD-CREDITS            PIC S9(15)V99 COMP-3.
           05  GL-STATUS                 PIC X(01).
               88  GL-ACTIVE-ACCT        VALUE 'A'.
               88  GL-INACTIVE-ACCT      VALUE 'I'.
               88  GL-SUSPENDED-ACCT     VALUE 'S'.
           05  GL-LAST-POST-DATE         PIC X(10).
           05  GL-LAST-UPDATE-TS         PIC X(26).
           05  FILLER                    PIC X(10).
