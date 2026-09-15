       CBL APOST,NODYNAM,RENT,ARITH(EXTEND),TRUNC(BIN)
       PROCESS LIST,MAP,XREF
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPDIR.
      *================================================================*
      * Program type: compiler-directive driven program.               *
      * CBL / PROCESS options lines, conditional compilation           *
      * (>>DEFINE, >>IF, >>EVALUATE, >>SOURCE FORMAT), TITLE, EJECT,   *
      * SKIP, debugging lines (D in column 7) under WITH DEBUGGING     *
      * MODE, REPLACE ... BY ... / REPLACE OFF, and a `/` page-eject   *
      * comment line.                                                  *
      *================================================================*
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-390 WITH DEBUGGING MODE.
       OBJECT-COMPUTER. IBM-390.
       TITLE 'COMPDIR - DIRECTIVE COVERAGE'
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       >>DEFINE ENVIRON AS 'PROD'
       >>DEFINE MAX-ROWS AS 500
       >>DEFINE TRACE-ON AS B'1'
       01  WS-ENV                  PIC X(4).
       01  WS-COUNTERS.
           05  WS-ROWS             PIC 9(5) COMP VALUE 0.
       >>IF ENVIRON = 'PROD'
           05  WS-LIMIT            PIC 9(5) COMP VALUE 500.
       >>ELSE
           05  WS-LIMIT            PIC 9(5) COMP VALUE 10.
       >>END-IF
       01  WS-TRACE-MSG            PIC X(30).
       EJECT
       PROCEDURE DIVISION.
       0000-MAIN.
       >>EVALUATE ENVIRON
       >>WHEN 'PROD'
           MOVE 'PROD' TO WS-ENV
       >>WHEN 'TEST'
           MOVE 'TEST' TO WS-ENV
       >>WHEN OTHER
           MOVE 'DEV ' TO WS-ENV
       >>END-EVALUATE
      D    DISPLAY 'DEBUG: ENVIRONMENT IS ' WS-ENV
           PERFORM 1000-COUNT-ROWS
       SKIP2
           PERFORM 2000-REPLACED-LOGIC
       >>IF TRACE-ON IS DEFINED
           MOVE 'TRACE ACTIVE' TO WS-TRACE-MSG
           DISPLAY WS-TRACE-MSG
       >>END-IF
           STOP RUN.
      /
       1000-COUNT-ROWS.
           PERFORM VARYING WS-ROWS FROM 1 BY 1
               UNTIL WS-ROWS > WS-LIMIT
      D        DISPLAY 'ROW ' WS-ROWS
               CONTINUE
           END-PERFORM.
       REPLACE ==:PFX:== BY ==WS==.
       2000-REPLACED-LOGIC.
           MOVE 0 TO :PFX:-ROWS
           IF :PFX:-ROWS = 0
               DISPLAY 'RESET'
           END-IF.
       REPLACE OFF.
