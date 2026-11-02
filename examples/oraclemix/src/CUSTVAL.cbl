       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTVAL.
      * CICS LINK TARGET: VALIDATES A CUSTOMER ID
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MAX-ID              PIC 9(6) VALUE 899999.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-CUST-ID         PIC 9(6).
           05  LK-RESULT          PIC X(2).
       PROCEDURE DIVISION.
       0000-MAIN.
           IF LK-CUST-ID NUMERIC AND LK-CUST-ID > 0
                   AND LK-CUST-ID NOT > WS-MAX-ID
               MOVE 'OK' TO LK-RESULT
           ELSE
               MOVE 'NO' TO LK-RESULT
           END-IF
           EXEC CICS RETURN END-EXEC.
