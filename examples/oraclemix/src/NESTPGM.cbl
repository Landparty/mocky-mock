       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTPGM.
      * INTEREST RUN WITH TWO CONTAINED (NESTED) PROGRAMS
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT BAL-IN  ASSIGN TO BALIN.
           SELECT BAL-OUT ASSIGN TO BALOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  BAL-IN.
       01  BAL-IN-REC.
           05  BI-CUST-ID         PIC 9(6).
           05  BI-BALANCE         PIC 9(7)V99.
       FD  BAL-OUT.
       01  BAL-OUT-LINE           PIC X(40).
       WORKING-STORAGE SECTION.
       01  WS-EOF                 PIC X VALUE 'N'.
       01  WS-INTEREST            PIC 9(7)V99.
       01  WS-LINE                PIC X(40).
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT BAL-IN
           OPEN OUTPUT BAL-OUT
           PERFORM UNTIL WS-EOF = 'Y'
               READ BAL-IN
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       CALL 'NESTCALC' USING BI-BALANCE WS-INTEREST
                       CALL 'NESTFMT' USING BI-CUST-ID WS-INTEREST
                                            WS-LINE
                       MOVE WS-LINE TO BAL-OUT-LINE
                       WRITE BAL-OUT-LINE
               END-READ
           END-PERFORM
           CLOSE BAL-IN
           CLOSE BAL-OUT
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTCALC.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-BALANCE             PIC 9(7)V99.
       01  LK-INTEREST            PIC 9(7)V99.
       PROCEDURE DIVISION USING LK-BALANCE LK-INTEREST.
       0000-CALC.
           IF LK-BALANCE > 10000
               COMPUTE LK-INTEREST ROUNDED = LK-BALANCE * 0.02
           ELSE
               COMPUTE LK-INTEREST ROUNDED = LK-BALANCE * 0.01
           END-IF
           GOBACK.
       END PROGRAM NESTCALC.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTFMT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-INT-ED              PIC Z(6)9.99.
       LINKAGE SECTION.
       01  LK-CUST-ID             PIC 9(6).
       01  LK-INTEREST            PIC 9(7)V99.
       01  LK-LINE                PIC X(40).
       PROCEDURE DIVISION USING LK-CUST-ID LK-INTEREST LK-LINE.
       0000-FMT.
           MOVE LK-INTEREST TO WS-INT-ED
           MOVE SPACES TO LK-LINE
           STRING LK-CUST-ID ' INTEREST ' WS-INT-ED
               DELIMITED BY SIZE INTO LK-LINE
           GOBACK.
       END PROGRAM NESTFMT.
       END PROGRAM NESTPGM.
