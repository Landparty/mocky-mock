       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNDRV.
      * PRICES INVOICES THROUGH A DYNAMICALLY CALLED RATE PROGRAM
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-IN  ASSIGN TO INVIN.
           SELECT INV-OUT ASSIGN TO INVOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  INV-IN.
       01  INV-IN-REC.
           05  II-CUST-ID         PIC 9(6).
           05  II-AMOUNT          PIC 9(7)V99.
       FD  INV-OUT.
       01  INV-OUT-REC.
           05  IO-CUST-ID         PIC 9(6).
           05  IO-AMOUNT          PIC 9(7)V99.
           05  IO-TAX             PIC 9(7)V99.
       WORKING-STORAGE SECTION.
       01  WS-RATE-PGM            PIC X(8) VALUE 'RATECALC'.
       01  WS-EOF                 PIC X VALUE 'N'.
       01  WS-RATE-AREA.
           05  RA-AMOUNT          PIC 9(7)V99.
           05  RA-TAX             PIC 9(7)V99.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT INV-IN
           OPEN OUTPUT INV-OUT
           PERFORM UNTIL WS-EOF = 'Y'
               READ INV-IN
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM 1000-PRICE
               END-READ
           END-PERFORM
           CLOSE INV-IN
           CLOSE INV-OUT
           GOBACK.
       1000-PRICE.
           MOVE II-AMOUNT TO RA-AMOUNT
           CALL WS-RATE-PGM USING WS-RATE-AREA
           MOVE II-CUST-ID TO IO-CUST-ID
           MOVE II-AMOUNT TO IO-AMOUNT
           MOVE RA-TAX TO IO-TAX
           WRITE INV-OUT-REC.
