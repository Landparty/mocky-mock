       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPROG IS INITIAL PROGRAM.
      *================================================================*
      * Program type: statically/dynamically called subprogram.        *
      * IS INITIAL, LINKAGE SECTION, BY REFERENCE / BY VALUE / BY      *
      * CONTENT parameters, RETURNING, secondary ENTRY points, GOBACK, *
      * a CANCEL-able worker called both statically and dynamically,   *
      * and a recursive contained program (IS RECURSIVE).              *
      *================================================================*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-WORK.
           05  WS-DYN-NAME         PIC X(8) VALUE 'RATECALC'.
           05  WS-RATE             PIC S9V9(6) COMP-3.
           05  WS-FACT-IN          PIC 9(2) COMP VALUE 5.
           05  WS-FACT-OUT         PIC 9(18) COMP.
           05  WS-RC               PIC S9(4) COMP.
       LINKAGE SECTION.
       01  LK-ACCOUNT.
           05  LK-ACCT-NO          PIC X(10).
           05  LK-BALANCE          PIC S9(9)V99 COMP-3.
       01  LK-DAYS                 PIC S9(4) COMP.
       01  LK-INTEREST             PIC S9(9)V99 COMP-3.
       01  LK-RETURN-CODE          PIC S9(4) COMP.
       01  LK-OPTION               PIC X.
       PROCEDURE DIVISION USING BY REFERENCE LK-ACCOUNT
                                BY VALUE LK-DAYS
                                BY REFERENCE LK-INTEREST
                          RETURNING LK-RETURN-CODE.
       0000-MAIN.
           IF LK-DAYS <= 0
               MOVE 8 TO LK-RETURN-CODE
               GOBACK
           END-IF
           CALL WS-DYN-NAME USING BY CONTENT LK-ACCT-NO
                                  BY REFERENCE WS-RATE
               ON EXCEPTION
                   MOVE 12 TO LK-RETURN-CODE
                   GOBACK
               NOT ON EXCEPTION
                   CONTINUE
           END-CALL
           COMPUTE LK-INTEREST ROUNDED =
               LK-BALANCE * WS-RATE * LK-DAYS / 365
           CALL 'FACTORL' USING WS-FACT-IN WS-FACT-OUT
           CANCEL WS-DYN-NAME
           MOVE 0 TO LK-RETURN-CODE
           GOBACK.
           ENTRY 'SUBPROG2' USING LK-ACCOUNT LK-OPTION.
           IF LK-OPTION = 'Z'
               MOVE ZERO TO LK-BALANCE
           END-IF
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FACTORL IS RECURSIVE.
       DATA DIVISION.
       LOCAL-STORAGE SECTION.
       01  LS-N-MINUS-1            PIC 9(2) COMP.
       01  LS-SUB-RESULT           PIC 9(18) COMP.
       LINKAGE SECTION.
       01  LK-N                    PIC 9(2) COMP.
       01  LK-RESULT               PIC 9(18) COMP.
       PROCEDURE DIVISION USING LK-N LK-RESULT.
       0000-FACT.
           IF LK-N <= 1
               MOVE 1 TO LK-RESULT
           ELSE
               COMPUTE LS-N-MINUS-1 = LK-N - 1
               CALL 'FACTORL' USING LS-N-MINUS-1 LS-SUB-RESULT
               COMPUTE LK-RESULT = LK-N * LS-SUB-RESULT
           END-IF
           GOBACK.
       END PROGRAM FACTORL.
       END PROGRAM SUBPROG.
