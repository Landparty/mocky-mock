       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYCALC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE          PIC 9(3)V99 VALUE 0.
       01  WS-OT            PIC 9(3) VALUE 0.
       LINKAGE SECTION.
       01  LK-PAY-AREA.
           05 LK-HOURS      PIC 9(3).
           05 LK-GRADE      PIC X(2).
           05 LK-GROSS      PIC 9(7)V99.
           05 LK-RC         PIC 9(2).
       PROCEDURE DIVISION USING LK-PAY-AREA.
       0000-CALC.
           MOVE 0 TO LK-RC
           IF LK-GRADE = 'A1'
               MOVE 12.50 TO WS-RATE
           ELSE
               MOVE 8 TO LK-RC
               MOVE 0 TO LK-GROSS
               GOBACK
           END-IF
           IF LK-HOURS > 40
               COMPUTE WS-OT = LK-HOURS - 40
               COMPUTE LK-GROSS = 40 * WS-RATE + WS-OT * WS-RATE * 1.5
           ELSE
               COMPUTE LK-GROSS = LK-HOURS * WS-RATE
           END-IF
           GOBACK.
