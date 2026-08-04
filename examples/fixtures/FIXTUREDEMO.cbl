       IDENTIFICATION DIVISION.
       PROGRAM-ID. FIXTUREDEMO.
      * Worked example for the gen-fixtures program-scoped test-data
      * initiative (Phase 9 of docs/plans/2026-08-02-program-data-
      * generation-*.md): one small program touching all four boundary
      * categories the initiative supports end to end -- file I/O
      * (OPEN/READ/CLOSE), SQL (a plain host-variable SELECT, no cursor,
      * so it stays clear of the DCLGEN EXEC SQL INCLUDE gap documented
      * for examples/custprog/ in the sibling mocky-mock repo), a static
      * CALL, and a console ACCEPT.
      *
      * Its generated FixtureBundle JSON (FIXTUREDEMO.bundle.json, seed
      * 42, mode "happy") and mocky-mock's generated .cut
      * (examples/fixtures/FIXTUREDEMO.cut over there) are both checked
      * in as goldens, each pinned by its own repo's byte-identical
      * regression test -- see tests/regression/test_fixturedemo_golden.py
      * here.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO "ORDERS"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-ORDER-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-RECORD.
           05  ORDER-ID            PIC X(6).
           05  ORDER-QTY           PIC 9(4).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-ORDER-STATUS         PIC XX.
       01  WS-EOF                  PIC X VALUE "N".
       01  WS-ORDER-TOTAL          PIC 9(6) VALUE 0.
       01  WS-CUSTOMER-ID          PIC X(6).
       01  WS-CUST-NAME            PIC X(30).
       01  WS-ALERT-STATUS         PIC X(2).

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           ACCEPT WS-CUSTOMER-ID.
           OPEN INPUT ORDER-FILE.
           PERFORM READ-ORDERS UNTIL WS-EOF = "Y".
           CLOSE ORDER-FILE.
           EXEC SQL
               SELECT CUST_NAME INTO :WS-CUST-NAME
               FROM CUSTOMERS WHERE CUST_ID = :WS-CUSTOMER-ID
           END-EXEC.
           CALL "LOGALERT" USING WS-ALERT-STATUS.
           GOBACK.

       READ-ORDERS.
           READ ORDER-FILE
               AT END
                   MOVE "Y" TO WS-EOF
               NOT AT END
                   ADD ORDER-QTY TO WS-ORDER-TOTAL
           END-READ.
