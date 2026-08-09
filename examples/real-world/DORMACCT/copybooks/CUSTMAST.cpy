      *****************************************************************
      * CUSTOMER MASTER RECORD LAYOUT                                *
      * COPYBOOK: CUSTMAST                                           *
      * DESCRIPTION: Banking customer master record structure        *
      * USED BY: ACCTMNT, LOANPMT, ACHPROC, STMTGEN, CTRRPT,      *
      *          DORMACCT                                            *
      *****************************************************************
       01  CUSTOMER-MASTER-RECORD.
           05  CUST-CIF-NUMBER           PIC X(10).
           05  CUST-TYPE                 PIC X(01).
               88  CUST-INDIVIDUAL       VALUE 'I'.
               88  CUST-BUSINESS         VALUE 'B'.
               88  CUST-TRUST            VALUE 'T'.
           05  CUST-NAME.
               10  CUST-FIRST-NAME      PIC X(25).
               10  CUST-MIDDLE-INIT     PIC X(01).
               10  CUST-LAST-NAME       PIC X(30).
           05  CUST-BUSINESS-NAME       PIC X(60).
           05  CUST-SSN                  PIC X(09).
           05  CUST-TIN                  PIC X(09).
           05  CUST-DOB                  PIC X(10).
           05  CUST-ADDRESS.
               10  CUST-ADDR-LINE1      PIC X(40).
               10  CUST-ADDR-LINE2      PIC X(40).
               10  CUST-CITY            PIC X(25).
               10  CUST-STATE           PIC X(02).
               10  CUST-ZIP             PIC X(10).
           05  CUST-PHONE-PRIMARY       PIC X(15).
           05  CUST-PHONE-MOBILE        PIC X(15).
           05  CUST-EMAIL               PIC X(60).
           05  CUST-KYC-STATUS          PIC X(01).
               88  CUST-KYC-VERIFIED    VALUE 'V'.
               88  CUST-KYC-PENDING     VALUE 'P'.
               88  CUST-KYC-FAILED      VALUE 'F'.
               88  CUST-KYC-EXPIRED     VALUE 'E'.
           05  CUST-KYC-DATE            PIC X(10).
           05  CUST-RISK-RATING         PIC X(01).
               88  CUST-RISK-LOW        VALUE 'L'.
               88  CUST-RISK-MEDIUM     VALUE 'M'.
               88  CUST-RISK-HIGH       VALUE 'H'.
           05  CUST-STATUS              PIC X(01).
               88  CUST-ACTIVE          VALUE 'A'.
               88  CUST-INACTIVE        VALUE 'I'.
               88  CUST-DECEASED        VALUE 'D'.
           05  CUST-RELATIONSHIP-DATE   PIC X(10).
           05  CUST-LAST-UPDATE-TS      PIC X(26).
           05  CUST-LAST-UPDATE-USER    PIC X(08).
           05  FILLER                   PIC X(15).
