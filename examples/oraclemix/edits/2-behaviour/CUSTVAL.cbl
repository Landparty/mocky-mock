       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTVAL.
      * CICS LINK TARGET: VALIDATES A CUSTOMER ID
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MAX-ID              PIC 9(6) VALUE 799999.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-CUST-ID         PIC 9(6).
           05  LK-RESULT          PIC X(2).
       PROCEDURE DIVISION.
       0000-MAIN.
           EVALUATE TRUE
               WHEN LK-CUST-ID NOT NUMERIC
               WHEN LK-CUST-ID = 0
               WHEN LK-CUST-ID > WS-MAX-ID
                   MOVE 'NO' TO LK-RESULT
               WHEN OTHER
                   MOVE 'OK' TO LK-RESULT
           END-EVALUATE
           EXEC CICS RETURN END-EXEC.
