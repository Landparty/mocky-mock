       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTPROG.
      * Cursor-driven customer lister: EXEC SQL INCLUDE resolves a
      * DCLGEN-style host-variable copybook (with its own embedded
      * EXEC SQL DECLARE TABLE stanza) into real WORKING-STORAGE data
      * items, then a DECLARE CURSOR/OPEN/FETCH-loop/CLOSE walks it,
      * driven entirely by a MOCK SQL "FETCH ..." ROWS block.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE CUSTREC END-EXEC.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-ROW-COUNT       PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           EXEC SQL
               DECLARE CUST_CURSOR CURSOR FOR
               SELECT CUST_ID, CUST_NAME FROM CUSTOMERS
           END-EXEC.
           EXEC SQL
               OPEN CUST_CURSOR
           END-EXEC.
           PERFORM FETCH-LOOP UNTIL WS-EOF = "Y".
           EXEC SQL
               CLOSE CUST_CURSOR
           END-EXEC.

       FETCH-LOOP.
           EXEC SQL
               FETCH CUST_CURSOR INTO :CUST-ID, :CUST-NAME
           END-EXEC.
           IF SQLCODE = 100
               MOVE "Y" TO WS-EOF
           ELSE
               ADD 1 TO WS-ROW-COUNT
           END-IF.
