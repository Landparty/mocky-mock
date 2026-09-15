       IDENTIFICATION DIVISION.
       PROGRAM-ID. COPYREPL.
      *================================================================*
      * Program type: copybook-heavy shop program.                     *
      * COPY with REPLACING pseudo-text (:PFX: tags), a copybook that  *
      * itself COPYs another (nested, no REPLACING -- the only nesting *
      * IBM allows), COPY ... OF library, COPY SUPPRESS,              *
      * a procedure-division COPY, and EXEC SQL INCLUDE of SQLCA and   *
      * a DCLGEN member.                                               *
      *================================================================*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE DCLCUST END-EXEC.
       01  WS-IN-CUSTOMER.
           COPY CUSTREC REPLACING ==:PFX:== BY ==IN==.
       01  WS-OUT-CUSTOMER.
           COPY CUSTREC REPLACING ==:PFX:== BY ==OUT==.
           COPY WSCOUNTS OF COPYLIB SUPPRESS.
       01  WS-DONE                 PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE 'C0000001' TO IN-CUST-ID
           MOVE 'ADA' TO IN-CUST-NAME
           SET IN-ACTIVE TO TRUE
           MOVE 'LONDON' TO IN-CITY
           MOVE WS-IN-CUSTOMER TO WS-OUT-CUSTOMER
           IF OUT-ACTIVE
               ADD 1 TO WS-WRITE-COUNT
           END-IF
           MOVE IN-CUST-ID TO CUST-ID
           EXEC SQL
               SELECT CUST_NAME, BALANCE
                 INTO :CUST-NAME, :BALANCE
                 FROM BANK.CUSTOMER
                WHERE CUST_ID = :CUST-ID
           END-EXEC
           IF SQLCODE NOT = 0
               ADD 1 TO WS-ERROR-COUNT
               PERFORM 8000-COMMON-ABEND
           END-IF
           SET WS-EOF TO TRUE
           DISPLAY OUT-CUST-NAME ' ' OUT-CITY ' ' CUST-NAME-TEXT
           GOBACK.
           COPY PROCLIB.
