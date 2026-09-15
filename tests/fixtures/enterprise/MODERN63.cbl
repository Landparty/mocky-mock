       IDENTIFICATION DIVISION.
       PROGRAM-ID. MODERN63.
      *================================================================*
      * Program type: Enterprise COBOL 6.x data-description program.   *
      * UTF-8 (PIC U, DYNAMIC LENGTH), NATIONAL, COMP-5, 64-bit        *
      * binary, floating point, POINTER / PROCEDURE-POINTER /          *
      * FUNCTION-POINTER, ALLOCATE / FREE, OCCURS UNBOUNDED, VOLATILE, *
      * SIGN SEPARATE, 66 RENAMES, SYNC, JUSTIFIED, BLANK WHEN ZERO,   *
      * hex/national/UTF-8 literals, EXIT PARAGRAPH/SECTION/PERFORM,   *
      * inline PERFORM WITH TEST AFTER, SEARCH ALL, INSPECT CONVERTING.*
      *================================================================*
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           SYMBOLIC CHARACTERS ESC IS 28
           CLASS HEX-DIGIT IS '0' THRU '9' 'A' THRU 'F'
           CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL 'E'.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-UTF8-NAME            PIC U(40).
       01  WS-UTF8-BYTES           PIC U BYTE-LENGTH 120.
       01  WS-UTF8-DYN             PIC U DYNAMIC LENGTH LIMIT 4000.
       01  WS-NATIONAL-NAME        PIC N(20) USAGE NATIONAL.
       01  WS-NATIONAL-NUM         PIC N(4) NATIONAL VALUE N'1234'.
       01  WS-BINARY-64            PIC S9(18) COMP.
       01  WS-NATIVE-BIN           PIC S9(9) COMP-5.
       01  WS-FLOAT-SHORT          COMP-1.
       01  WS-FLOAT-LONG           COMP-2.
       01  WS-PACKED-31            PIC S9(29)V99 COMP-3.
       01  WS-SIGN-SEP             PIC S9(7)V99 SIGN LEADING SEPARATE.
       01  WS-EURO                 PIC E(1)Z(6)9.99.
       01  WS-BLANK-ZERO           PIC Z(5)9 BLANK WHEN ZERO.
       01  WS-JUSTIFIED            PIC X(20) JUSTIFIED RIGHT.
       01  WS-VOLATILE             PIC X(8) VOLATILE.
       01  WS-HEX-LIT              PIC X(4) VALUE X'C1C2C3C4'.
       01  WS-NULL-TERM            PIC X(6) VALUE Z'HELLO'.
       01  WS-UTF8-LIT             PIC U(10) VALUE U'ÄÖÜ'.
       01  WS-ADDRESS              USAGE POINTER.
       01  WS-ADDRESS-64           USAGE POINTER-64.
       01  WS-PROC-PTR             USAGE PROCEDURE-POINTER.
       01  WS-FUNC-PTR             USAGE FUNCTION-POINTER.
       01  WS-INDEX-ITEM           USAGE INDEX.
       01  WS-SYNC-GROUP.
           05  WS-SYNC-CHAR        PIC X.
           05  WS-SYNC-BIN         PIC S9(9) COMP SYNC.
           05  WS-SYNC-PACKED      PIC S9(7) COMP-3 SYNCHRONIZED.
       01  WS-DATE-PARTS.
           05  WS-YEAR             PIC 9(4).
           05  WS-MONTH            PIC 99.
           05  WS-DAY              PIC 99.
       66  WS-YEAR-MONTH RENAMES WS-YEAR THRU WS-MONTH.
       01  WS-RATE-TABLE.
           05  WS-RATE-COUNT       PIC 9(4) COMP.
           05  WS-RATE-ENTRY OCCURS 1 TO 500 TIMES
                                   DEPENDING ON WS-RATE-COUNT
                                   ASCENDING KEY IS WS-RATE-CODE
                                   INDEXED BY WS-RATE-IDX.
               10  WS-RATE-CODE    PIC X(4).
               10  WS-RATE-VALUE   PIC S9V9(6) COMP-3.
       01  WS-UNBOUNDED-GROUP.
           05  WS-ROW-COUNT        PIC 9(9) COMP.
           05  WS-ROW OCCURS UNBOUNDED DEPENDING ON WS-ROW-COUNT.
               10  WS-ROW-KEY      PIC X(8).
               10  WS-ROW-DATA     PIC X(72).
       01  WS-SEARCH-CODE          PIC X(4).
       01  WS-FOUND                PIC X VALUE 'N'.
       01  WS-RETRIES              PIC 9 VALUE 0.
       01  WS-TEXT                 PIC X(30) VALUE 'hello, world'.
       LINKAGE SECTION.
       01  LK-DYNAMIC-AREA.
           05  LK-DYN-LEN          PIC 9(9) COMP.
           05  LK-DYN-TEXT         PIC X(1000).
       PROCEDURE DIVISION.
       MAIN-SECTION SECTION.
       0000-MAIN.
           PERFORM 1000-ALLOCATE-AREA
           PERFORM 2000-SEARCH-RATES
           PERFORM 3000-CHARACTER-WORK
           PERFORM 4000-LOOP-FORMS
           GOBACK.
       1000-ALLOCATE-AREA.
           ALLOCATE 1004 CHARACTERS INITIALIZED RETURNING WS-ADDRESS
           SET ADDRESS OF LK-DYNAMIC-AREA TO WS-ADDRESS
           MOVE 1000 TO LK-DYN-LEN
           MOVE ALL 'X' TO LK-DYN-TEXT
           SET WS-ADDRESS-64 TO ADDRESS OF LK-DYN-TEXT
           SET WS-PROC-PTR TO ENTRY 'SUBPROG'
           SET WS-FUNC-PTR TO ENTRY 'RATECALC'
           IF WS-ADDRESS NOT = NULL
               FREE WS-ADDRESS
           END-IF.
       2000-SEARCH-RATES.
           MOVE 3 TO WS-RATE-COUNT
           MOVE 'AAAA' TO WS-RATE-CODE(1)
           MOVE 'BBBB' TO WS-RATE-CODE(2)
           MOVE 'CCCC' TO WS-RATE-CODE(3)
           MOVE 'BBBB' TO WS-SEARCH-CODE
           SEARCH ALL WS-RATE-ENTRY
               AT END MOVE 'N' TO WS-FOUND
               WHEN WS-RATE-CODE(WS-RATE-IDX) = WS-SEARCH-CODE
                   MOVE 'Y' TO WS-FOUND
                   SET WS-INDEX-ITEM TO WS-RATE-IDX
           END-SEARCH
           IF WS-FOUND = 'N'
               EXIT PARAGRAPH
           END-IF
           DISPLAY 'RATE ' WS-RATE-VALUE(WS-RATE-IDX).
       3000-CHARACTER-WORK.
           MOVE FUNCTION DISPLAY-OF(WS-NATIONAL-NUM) TO WS-TEXT
           MOVE FUNCTION NATIONAL-OF(WS-TEXT 1208) TO WS-NATIONAL-NAME
           MOVE FUNCTION UTF8-OF(WS-NATIONAL-NAME) TO WS-UTF8-NAME
           MOVE WS-UTF8-NAME TO WS-UTF8-DYN
           INSPECT WS-TEXT CONVERTING 'abcdefghijklmnopqrstuvwxyz'
                                   TO 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
           INSPECT WS-TEXT TALLYING WS-RETRIES FOR ALL 'L'
           IF WS-TEXT(1:1) IS HEX-DIGIT
               CONTINUE
           END-IF
           MOVE 20260915 TO WS-DATE-PARTS
           DISPLAY WS-YEAR-MONTH
           MOVE 1234567.89 TO WS-SIGN-SEP WS-EURO WS-PACKED-31
           MOVE 0 TO WS-BLANK-ZERO
           MOVE WS-TEXT TO WS-JUSTIFIED
           COMPUTE WS-FLOAT-LONG = WS-FLOAT-SHORT * 1.5E+2
           COMPUTE WS-BINARY-64 = FUNCTION LENGTH(WS-UTF8-DYN)
           MOVE FUNCTION BYTE-LENGTH(WS-UTF8-BYTES) TO WS-NATIVE-BIN.
       4000-LOOP-FORMS.
           MOVE 0 TO WS-RETRIES
           PERFORM WITH TEST AFTER
               VARYING WS-RETRIES FROM 1 BY 1 UNTIL WS-RETRIES >= 3
               IF WS-RETRIES = 2
                   EXIT PERFORM CYCLE
               END-IF
               IF WS-FOUND = 'Y'
                   EXIT PERFORM
               END-IF
           END-PERFORM
           PERFORM 3 TIMES
               ADD 1 TO WS-ROW-COUNT
           END-PERFORM
           EXIT SECTION.
