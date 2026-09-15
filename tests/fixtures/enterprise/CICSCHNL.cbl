       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSCHNL.
      *================================================================*
      * Program type: CICS channel/container service program.          *
      * Receives a JSON request through a container, calls a web       *
      * service with INVOKE SERVICE, writes to a TS queue, starts an   *
      * async transaction and returns the reply in a container.        *
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP                 PIC S9(8) COMP.
       01  WS-CHANNEL              PIC X(16) VALUE 'ORDER-CHANNEL'.
       01  WS-REQ-CONTAINER        PIC X(16) VALUE 'REQUEST'.
       01  WS-RSP-CONTAINER        PIC X(16) VALUE 'RESPONSE'.
       01  WS-REQ-LEN              PIC S9(8) COMP.
       01  WS-REQUEST-JSON         PIC X(2000).
       01  WS-RESPONSE-JSON        PIC X(2000).
       01  WS-JSON-LEN             PIC 9(5) COMP.
       01  WS-ORDER.
           05  ORDER-ID            PIC X(12).
           05  ORDER-CUST          PIC X(8).
           05  ORDER-TOTAL         PIC 9(7)V99.
           05  ORDER-ITEMS         OCCURS 1 TO 20 TIMES
                                   DEPENDING ON ORDER-ITEM-COUNT.
               10  ITEM-SKU        PIC X(10).
               10  ITEM-QTY        PIC 9(4).
           05  ORDER-ITEM-COUNT    PIC 9(2).
       01  WS-CREDIT-REQ.
           05  CR-CUST             PIC X(8).
           05  CR-AMOUNT           PIC 9(7)V99.
       01  WS-CREDIT-RSP.
           05  CR-APPROVED         PIC X.
           05  CR-REASON           PIC X(40).
       01  WS-TSQ-NAME             PIC X(8) VALUE 'ORDRLOG'.
       01  WS-TSQ-ITEM             PIC S9(4) COMP.
       PROCEDURE DIVISION.
       0000-MAIN.
           EXEC CICS GET CONTAINER(WS-REQ-CONTAINER)
               CHANNEL(WS-CHANNEL)
               INTO(WS-REQUEST-JSON)
               FLENGTH(WS-REQ-LEN)
               RESP(WS-RESP)
           END-EXEC
           IF WS-RESP NOT = DFHRESP(NORMAL)
               EXEC CICS ABEND ABCODE('CHN1') END-EXEC
           END-IF
           JSON PARSE WS-REQUEST-JSON INTO WS-ORDER
               ON EXCEPTION
                   MOVE 'N' TO CR-APPROVED
                   MOVE 'MALFORMED REQUEST' TO CR-REASON
               NOT ON EXCEPTION
                   PERFORM 1000-CHECK-CREDIT
           END-JSON
           PERFORM 2000-LOG-TO-TSQ
           JSON GENERATE WS-RESPONSE-JSON FROM WS-CREDIT-RSP
               COUNT IN WS-JSON-LEN
               NAME OF CR-APPROVED IS 'approved'
                       CR-REASON IS 'reason'
           END-JSON
           EXEC CICS PUT CONTAINER(WS-RSP-CONTAINER)
               CHANNEL(WS-CHANNEL)
               FROM(WS-RESPONSE-JSON)
               FLENGTH(WS-JSON-LEN)
               DATATYPE(DFHVALUE(CHAR))
           END-EXEC
           EXEC CICS RETURN END-EXEC.
       1000-CHECK-CREDIT.
           MOVE ORDER-CUST TO CR-CUST
           MOVE ORDER-TOTAL TO CR-AMOUNT
           EXEC CICS PUT CONTAINER('DFHWS-DATA')
               CHANNEL('CREDIT-CHAN')
               FROM(WS-CREDIT-REQ)
           END-EXEC
           EXEC CICS INVOKE SERVICE('creditCheck')
               CHANNEL('CREDIT-CHAN')
               OPERATION('checkCredit')
               RESP(WS-RESP)
           END-EXEC
           IF WS-RESP = DFHRESP(NORMAL)
               EXEC CICS GET CONTAINER('DFHWS-DATA')
                   CHANNEL('CREDIT-CHAN')
                   INTO(WS-CREDIT-RSP)
               END-EXEC
           ELSE
               MOVE 'N' TO CR-APPROVED
               MOVE 'CREDIT SERVICE UNAVAILABLE' TO CR-REASON
           END-IF
           IF CR-APPROVED = 'Y'
               EXEC CICS START TRANSID('OFUL')
                   CHANNEL(WS-CHANNEL)
               END-EXEC
               EXEC CICS SYNCPOINT END-EXEC
           END-IF.
       2000-LOG-TO-TSQ.
           EXEC CICS WRITEQ TS QUEUE(WS-TSQ-NAME)
               FROM(WS-ORDER)
               LENGTH(LENGTH OF WS-ORDER)
               ITEM(WS-TSQ-ITEM)
               MAIN
               RESP(WS-RESP)
           END-EXEC.
