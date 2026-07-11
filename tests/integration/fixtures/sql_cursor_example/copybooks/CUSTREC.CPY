           EXEC SQL DECLARE CUSTOMERS TABLE
           ( CUST_ID     INTEGER NOT NULL,
             CUST_NAME   CHAR(30) )
           END-EXEC.
       01  CUSTREC.
           05  CUST-ID         PIC S9(9) COMP-5.
           05  CUST-NAME       PIC X(30).
