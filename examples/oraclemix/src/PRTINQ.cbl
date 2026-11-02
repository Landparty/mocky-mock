       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRTINQ.
      * IMS MPP: part availability inquiry. For each message on the
      * queue, PRTSTK reads the stock from DB2 and PRTRATE reads the
      * shipping lead time from a rate file; the reply goes back on
      * the IO-PCB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GU                  PIC X(4) VALUE "GU  ".
       01  DLI-ISRT                PIC X(4) VALUE "ISRT".
       01  WS-NO-MORE-MSGS         PIC X VALUE "N".
           88  NO-MORE-MSGS        VALUE "Y".
       COPY INQMSG.
       01  REPLY-MSG.
           05  REPLY-LL            PIC S9(4) COMP VALUE 60.
           05  REPLY-ZZ            PIC S9(4) COMP VALUE 0.
           05  REPLY-PART          PIC X(8).
           05  REPLY-STATUS        PIC X(10).
           05  REPLY-ONHAND        PIC 9(7).
           05  REPLY-DAYS          PIC 9(3).
           05  FILLER              PIC X(28).
       01  WS-STK-RC               PIC 9(2) VALUE 0.
       01  WS-ONHAND               PIC 9(7) VALUE 0.
       01  WS-RATE-RC              PIC 9(2) VALUE 0.
       01  WS-DAYS                 PIC 9(3) VALUE 0.
       01  WS-MSG-COUNT            PIC 9(5) VALUE 0.
       LINKAGE SECTION.
       01  IOPCB.
           05  IOPCB-LTERM         PIC X(8).
           05  FILLER              PIC XX.
           05  IOPCB-STATUS        PIC XX.
           05  FILLER              PIC X(20).
       PROCEDURE DIVISION.
       ENTRY 'DLITCBL' USING IOPCB.
       0000-MAIN.
           PERFORM 1000-GET-MSG
           PERFORM UNTIL NO-MORE-MSGS
               PERFORM 2000-PROCESS
               PERFORM 1000-GET-MSG
           END-PERFORM
           GOBACK.
       1000-GET-MSG.
           CALL 'CBLTDLI' USING DLI-GU IOPCB INQ-MSG
           IF IOPCB-STATUS NOT = SPACES
               SET NO-MORE-MSGS TO TRUE
           END-IF.
       2000-PROCESS.
           ADD 1 TO WS-MSG-COUNT
           MOVE INQ-PART TO REPLY-PART
           MOVE 0 TO WS-ONHAND WS-DAYS
           CALL 'PRTSTK' USING INQ-PART WS-ONHAND WS-STK-RC
           EVALUATE TRUE
               WHEN WS-STK-RC NOT = 0
                   MOVE "UNKNOWN" TO REPLY-STATUS
               WHEN WS-ONHAND >= INQ-QTY
                   MOVE "IN STOCK" TO REPLY-STATUS
               WHEN OTHER
                   CALL 'PRTRATE' USING INQ-PART WS-DAYS WS-RATE-RC
                   IF WS-RATE-RC = 0
                       MOVE "BACKORDER" TO REPLY-STATUS
                   ELSE
                       MOVE "NO SOURCE" TO REPLY-STATUS
                   END-IF
           END-EVALUATE
           MOVE WS-ONHAND TO REPLY-ONHAND
           MOVE WS-DAYS TO REPLY-DAYS
           CALL 'CBLTDLI' USING DLI-ISRT IOPCB REPLY-MSG.
