      *****************************************************************
      * STATEMENT RECORD LAYOUT                                      *
      * COPYBOOK: STMTREC                                            *
      * DESCRIPTION: Monthly account statement record structure      *
      * USED BY: STMTGEN, STMTFMT (PL/I)                           *
      *****************************************************************
       01  STATEMENT-HEADER-RECORD.
           05  STMT-RECORD-TYPE          PIC X(01).
               88  STMT-IS-HEADER        VALUE 'H'.
               88  STMT-IS-DETAIL        VALUE 'D'.
               88  STMT-IS-SUMMARY       VALUE 'S'.
           05  STMT-ACCT-NUMBER          PIC X(12).
           05  STMT-CUST-NAME            PIC X(56).
           05  STMT-ADDRESS.
               10  STMT-ADDR-LINE1      PIC X(40).
               10  STMT-ADDR-LINE2      PIC X(40).
               10  STMT-CITY            PIC X(25).
               10  STMT-STATE           PIC X(02).
               10  STMT-ZIP             PIC X(10).
           05  STMT-PERIOD-BEGIN         PIC X(10).
           05  STMT-PERIOD-END           PIC X(10).
           05  STMT-OPENING-BALANCE      PIC S9(13)V99 COMP-3.
           05  STMT-CLOSING-BALANCE      PIC S9(13)V99 COMP-3.
           05  STMT-TOTAL-DEBITS         PIC S9(13)V99 COMP-3.
           05  STMT-TOTAL-CREDITS        PIC S9(13)V99 COMP-3.
           05  STMT-TOTAL-FEES           PIC S9(09)V99 COMP-3.
           05  STMT-INTEREST-EARNED      PIC S9(09)V99 COMP-3.
           05  STMT-AVG-DAILY-BALANCE    PIC S9(13)V99 COMP-3.
           05  STMT-TRAN-COUNT           PIC 9(05).
           05  STMT-PAGE-COUNT           PIC 9(03).
      *
       01  STATEMENT-DETAIL-RECORD.
           05  STDT-RECORD-TYPE          PIC X(01) VALUE 'D'.
           05  STDT-ACCT-NUMBER          PIC X(12).
           05  STDT-TRAN-DATE            PIC X(10).
           05  STDT-POST-DATE            PIC X(10).
           05  STDT-TRAN-CODE            PIC X(04).
           05  STDT-DESCRIPTION          PIC X(40).
           05  STDT-REFERENCE            PIC X(20).
           05  STDT-DEBIT-AMOUNT         PIC S9(13)V99 COMP-3.
           05  STDT-CREDIT-AMOUNT        PIC S9(13)V99 COMP-3.
           05  STDT-RUNNING-BALANCE      PIC S9(13)V99 COMP-3.
           05  STDT-CHECK-NUMBER         PIC X(10).
           05  STDT-LINE-NUMBER          PIC 9(05).
