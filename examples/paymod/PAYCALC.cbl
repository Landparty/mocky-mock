       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYCALC.
      * In-module subprogram: looks the grade's hourly rate up in DB2
      * and prices the hours, time and a half past 40.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-RATE             PIC 9(3)V99 VALUE 0.
       01  WS-OVERTIME         PIC 9(3) VALUE 0.
       01  WS-CALLS            PIC 9(5) VALUE 0.
       LINKAGE SECTION.
       01  LK-PAY-AREA.
           05  LK-HOURS        PIC 9(3).
           05  LK-GRADE        PIC X(2).
           05  LK-GROSS        PIC 9(7)V99.
           05  LK-RC           PIC 9(2).
       PROCEDURE DIVISION USING LK-PAY-AREA.
       0000-CALC.
           ADD 1 TO WS-CALLS
           EXEC SQL
               SELECT HOURLY_RATE INTO :WS-RATE
                 FROM PAY_GRADE
                WHERE GRADE = :LK-GRADE
           END-EXEC
           IF SQLCODE NOT = 0
               MOVE 8 TO LK-RC
               MOVE 0 TO LK-GROSS
               GOBACK
           END-IF
           MOVE 0 TO LK-RC
           IF LK-HOURS > 40
               COMPUTE WS-OVERTIME = LK-HOURS - 40
               COMPUTE LK-GROSS = (40 * WS-RATE)
                   + (WS-OVERTIME * WS-RATE * 1.5)
           ELSE
               COMPUTE LK-GROSS = LK-HOURS * WS-RATE
           END-IF
           GOBACK.
