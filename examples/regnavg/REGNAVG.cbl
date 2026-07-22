       IDENTIFICATION DIVISION.
       PROGRAM-ID. REGNAVG.
      * Computes one region's average of three monthly sales amounts and
      * calls a notification subprogram when that average exceeds a
      * threshold. Region 1 and region 2 are computed by separate
      * paragraphs (not a single loop over both) deliberately -- each test
      * case PERFORMs only one region's paragraph, so the OTHER region's
      * average is never recomputed in that run and reading it back
      * proves cross-case reset actually happened, not just that this
      * run's own arithmetic overwrote it. Exercises a two-dimensional
      * OCCURS table, a REDEFINES group (two siblings aliasing the same
      * average field), and DIVIDE ... GIVING ... ROUNDED.
      *
      * DIVIDE targets an unsubscripted scratch field, then MOVEs it into
      * the table cell -- confirmed directly against the exact pinned
      * cobolparser commit (4db8394, "consume ROUNDED after DIVIDE/
      * MULTIPLY GIVING") that a *subscripted* GIVING target still warns
      * PARSE_WARNING there; that support only lands two commits later
      * (4917576, "fix silent data loss in ... arithmetic clauses"), not
      * yet adopted by this repo's pin. CALL "LOGALERT" likewise never
      * takes the subscripted average as an argument -- CALL ... USING
      * with a subscripted operand outside a PERFORM VARYING body is a
      * separate, still-open gap at every commit tested.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REGION-COUNT         PIC 9(1) VALUE 3.
       01  WS-THRESHOLD            PIC 9(5)V99 VALUE 75.00.
       01  WS-REGION-TABLE.
           05  WS-REGION OCCURS 2 TIMES.
               10  WS-MONTH-AMT OCCURS 3 TIMES PIC 9(5)V99.
       01  WS-REGION-AVG-TABLE.
           05  WS-REGION-AVG-GROUP OCCURS 2 TIMES.
               10  WS-REGION-AVG              PIC 9(5)V99.
               10  WS-REGION-AVG-DISPLAY REDEFINES WS-REGION-AVG
                       PIC X(7).
               10  WS-REGION-AVG-NUMERIC REDEFINES WS-REGION-AVG
                       PIC 9(7).
       01  WS-REGION-AVG-SCRATCH   PIC 9(5)V99.
       01  WS-REGION-TOTAL         PIC 9(6)V99.
       01  WS-MONTH-IDX            PIC 9(1).
       01  WS-ALERT-STATUS         PIC X(2).

       PROCEDURE DIVISION.
       1000-CALCULATE-REGION-1-AVERAGE.
           MOVE 0 TO WS-REGION-TOTAL.
           PERFORM VARYING WS-MONTH-IDX FROM 1 BY 1
                   UNTIL WS-MONTH-IDX > 3
               ADD WS-MONTH-AMT(1, WS-MONTH-IDX) TO WS-REGION-TOTAL
           END-PERFORM.
           DIVIDE WS-REGION-TOTAL BY WS-REGION-COUNT
               GIVING WS-REGION-AVG-SCRATCH ROUNDED.
           MOVE WS-REGION-AVG-SCRATCH TO WS-REGION-AVG(1).
           IF WS-REGION-AVG-SCRATCH > WS-THRESHOLD
               CALL "LOGALERT" USING WS-ALERT-STATUS
           END-IF.
           GOBACK.

       2000-CALCULATE-REGION-2-AVERAGE.
           MOVE 0 TO WS-REGION-TOTAL.
           PERFORM VARYING WS-MONTH-IDX FROM 1 BY 1
                   UNTIL WS-MONTH-IDX > 3
               ADD WS-MONTH-AMT(2, WS-MONTH-IDX) TO WS-REGION-TOTAL
           END-PERFORM.
           DIVIDE WS-REGION-TOTAL BY WS-REGION-COUNT
               GIVING WS-REGION-AVG-SCRATCH ROUNDED.
           MOVE WS-REGION-AVG-SCRATCH TO WS-REGION-AVG(2).
           IF WS-REGION-AVG-SCRATCH > WS-THRESHOLD
               CALL "LOGALERT" USING WS-ALERT-STATUS
           END-IF.
           GOBACK.
