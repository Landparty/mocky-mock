       IDENTIFICATION DIVISION.
       PROGRAM-ID. XMLJSON.
      *================================================================*
      * Program type: XML / JSON message handling program.             *
      * XML PARSE with a PROCESSING PROCEDURE reading the XML-EVENT /  *
      * XML-TEXT / XML-NTEXT special registers, XML GENERATE with      *
      * NAMESPACE and ATTRIBUTES, JSON GENERATE with NAME/SUPPRESS,    *
      * and JSON PARSE with WITH DETAIL.                               *
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-XML-DOCUMENT         PIC X(4000).
       01  WS-XML-OUT              PIC X(4000).
       01  WS-XML-LEN              PIC 9(5) COMP.
       01  WS-JSON-OUT             PIC X(2000).
       01  WS-JSON-IN              PIC X(2000).
       01  WS-JSON-LEN             PIC 9(5) COMP.
       01  WS-CURRENT-ELEMENT      PIC X(30).
       01  WS-ORDER.
           05  ORDER-ID            PIC X(12).
           05  ORDER-DATE          PIC X(10).
           05  ORDER-CUSTOMER.
               10  CUST-ID         PIC X(8).
               10  CUST-NAME       PIC X(30).
           05  ORDER-LINE-COUNT    PIC 99.
           05  ORDER-LINES OCCURS 1 TO 10 TIMES
                                   DEPENDING ON ORDER-LINE-COUNT.
               10  LINE-SKU        PIC X(10).
               10  LINE-QTY        PIC 9(4).
               10  LINE-PRICE      PIC 9(7)V99.
           05  ORDER-INTERNAL-FLAG PIC X.
       01  WS-NAMESPACE            PIC X(40)
                                   VALUE 'http://bank.example.com/o'.
       01  WS-XML-CODE-SAVE        PIC S9(9) COMP.
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE '<order id="A1"><customer>ADA</customer></order>'
             TO WS-XML-DOCUMENT
           XML PARSE WS-XML-DOCUMENT
               WITH ENCODING 1208
               RETURNING NATIONAL
               VALIDATING WITH FILE 'ORDERXSD'
               PROCESSING PROCEDURE 1000-XML-HANDLER
               ON EXCEPTION
                   MOVE XML-CODE TO WS-XML-CODE-SAVE
                   DISPLAY 'XML PARSE FAILED ' WS-XML-CODE-SAVE
               NOT ON EXCEPTION
                   PERFORM 2000-GENERATE-XML
           END-XML
           PERFORM 3000-JSON-ROUND-TRIP
           GOBACK.
       1000-XML-HANDLER.
           EVALUATE XML-EVENT
               WHEN 'START-OF-ELEMENT'
                   MOVE XML-TEXT TO WS-CURRENT-ELEMENT
               WHEN 'ATTRIBUTE-NAME'
                   CONTINUE
               WHEN 'ATTRIBUTE-CHARACTERS'
                   IF WS-CURRENT-ELEMENT = 'order'
                       MOVE XML-TEXT TO ORDER-ID
                   END-IF
               WHEN 'CONTENT-CHARACTERS'
                   EVALUATE WS-CURRENT-ELEMENT
                       WHEN 'customer' MOVE XML-NTEXT TO CUST-NAME
                       WHEN 'sku'      MOVE XML-TEXT TO LINE-SKU(1)
                   END-EVALUATE
               WHEN 'END-OF-ELEMENT'
                   MOVE SPACES TO WS-CURRENT-ELEMENT
               WHEN 'EXCEPTION'
                   MOVE -1 TO XML-CODE
               WHEN OTHER
                   CONTINUE
           END-EVALUATE.
       2000-GENERATE-XML.
           XML GENERATE WS-XML-OUT FROM WS-ORDER
               COUNT IN WS-XML-LEN
               WITH ENCODING 1208
               WITH XML-DECLARATION
               WITH ATTRIBUTES
               NAMESPACE IS WS-NAMESPACE
               NAMESPACE-PREFIX IS 'ord'
               NAME OF WS-ORDER IS 'Order'
                       ORDER-ID IS 'id'
               TYPE OF LINE-PRICE IS NUMERIC
               SUPPRESS ORDER-INTERNAL-FLAG
                        EVERY NONNUMERIC ELEMENT WHEN SPACE
               ON EXCEPTION
                   DISPLAY 'XML GENERATE FAILED ' XML-CODE
           END-XML.
       3000-JSON-ROUND-TRIP.
           JSON GENERATE WS-JSON-OUT FROM WS-ORDER
               COUNT IN WS-JSON-LEN
               NAME OF ORDER-ID IS 'orderId'
                       CUST-NAME IS 'customerName'
               SUPPRESS ORDER-INTERNAL-FLAG
               CONVERTING LINE-PRICE TO JSON DECIMAL
               ON EXCEPTION
                   DISPLAY 'JSON GENERATE FAILED ' JSON-CODE
           END-JSON
           MOVE WS-JSON-OUT TO WS-JSON-IN
           JSON PARSE WS-JSON-IN INTO WS-ORDER
               WITH DETAIL
               NAME OF ORDER-ID IS 'orderId'
               SUPPRESS ORDER-INTERNAL-FLAG
               ON EXCEPTION
                   DISPLAY 'JSON PARSE FAILED ' JSON-CODE ' '
                           JSON-STATUS
               NOT ON EXCEPTION
                   DISPLAY 'ROUND TRIP OK ' ORDER-ID
           END-JSON.
