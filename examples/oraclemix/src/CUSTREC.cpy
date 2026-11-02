      * CUSTOMER RECORD, SHARED BY BATCH, VSAM, DB2, CICS AND IMS
           05  CUST-ID            PIC 9(6).
           05  CUST-NAME          PIC X(20).
           05  CUST-BAL           PIC S9(7)V99 COMP-3.
           05  CUST-STATUS        PIC X.
               88  CUST-ACTIVE    VALUE 'A'.
               88  CUST-HELD      VALUE 'H'.
