       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDVAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-LIMIT                PIC S9(7)V99 COMP-3 VALUE 0.
       01  WS-CUST                 PIC X(6).
       01  WS-MSG                  PIC X(40).
       LINKAGE SECTION.
       COPY ORDREC REPLACING LEADING ==ORD-== BY ==LK-==.
       01  LK-RC                   PIC 9(2).
       PROCEDURE DIVISION USING LK-REC LK-RC.
       0000-VALIDATE.
           MOVE LK-CUST TO WS-CUST
           EXEC SQL
               SELECT CREDIT_LIMIT INTO :WS-LIMIT
                 FROM CUSTOMER
                WHERE CUST_ID = :WS-CUST
           END-EXEC
           EVALUATE TRUE
               WHEN SQLCODE NOT = 0
                   MOVE 8 TO LK-RC
                   MOVE "CUSTOMER NOT FOUND" TO WS-MSG
               WHEN LK-AMOUNT > WS-LIMIT
                   MOVE 4 TO LK-RC
                   MOVE "OVER CREDIT LIMIT" TO WS-MSG
               WHEN OTHER
                   MOVE 0 TO LK-RC
                   MOVE "OK" TO WS-MSG
           END-EVALUATE
           CALL "ORDLOG" USING LK-ID WS-MSG
           GOBACK.
