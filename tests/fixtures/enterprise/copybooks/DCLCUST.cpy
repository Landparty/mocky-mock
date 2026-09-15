           EXEC SQL DECLARE BANK.CUSTOMER TABLE
               ( CUST_ID        CHAR(8)        NOT NULL,
                 CUST_NAME      VARCHAR(30)    NOT NULL,
                 BALANCE        DECIMAL(11, 2) NOT NULL
               ) END-EXEC.
       01  DCLCUSTOMER.
           10  CUST-ID             PIC X(8).
           10  CUST-NAME.
               49  CUST-NAME-LEN   PIC S9(4) USAGE COMP.
               49  CUST-NAME-TEXT  PIC X(30).
           10  BALANCE             PIC S9(9)V99 USAGE COMP-3.
