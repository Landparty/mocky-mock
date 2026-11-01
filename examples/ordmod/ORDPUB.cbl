       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDPUB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-HCONN                PIC S9(9) BINARY VALUE 0.
       01  WS-HOBJ                 PIC S9(9) BINARY VALUE 0.
       01  WS-OPTIONS              PIC S9(9) BINARY VALUE 0.
       01  WS-COMPCODE             PIC S9(9) BINARY VALUE 0.
       01  WS-REASON               PIC S9(9) BINARY VALUE 0.
       01  WS-OBJDESC              PIC X(100) VALUE "ORDERS.OUT".
       01  WS-MSGDESC              PIC X(100).
       01  WS-PMO                  PIC X(100).
       01  WS-BUFLEN               PIC S9(9) BINARY VALUE 20.
       01  WS-BUFFER               PIC X(20).
       01  WS-PUBLISHED            PIC 9(5) VALUE 0.
       LINKAGE SECTION.
       COPY ORDREC REPLACING LEADING ==ORD-== BY ==LK-==.
       PROCEDURE DIVISION USING LK-REC.
       0000-PUBLISH.
           CALL "MQOPEN" USING WS-HCONN WS-OBJDESC WS-OPTIONS
                               WS-HOBJ WS-COMPCODE WS-REASON
           IF WS-COMPCODE = 0
               MOVE LK-REC TO WS-BUFFER
               CALL "MQPUT" USING WS-HCONN WS-HOBJ WS-MSGDESC WS-PMO
                                  WS-BUFLEN WS-BUFFER
                                  WS-COMPCODE WS-REASON
               IF WS-COMPCODE = 0
                   ADD 1 TO WS-PUBLISHED
                   EXEC SQL
                       UPDATE ORDERS SET STATUS = 'P'
                        WHERE ORDER_ID = :LK-ID
                   END-EXEC
               END-IF
               CALL "MQCLOSE" USING WS-HCONN WS-HOBJ WS-OPTIONS
                                    WS-COMPCODE WS-REASON
           END-IF
           GOBACK.
