       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYMAIN.
      * Load-module entry point: reads employees, has PAYCALC price
      * each one, and stamps the run date from DATEUTL (outside the
      * load module).
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMP-FILE ASSIGN TO EMPIN
               FILE STATUS IS WS-EMP-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  EMP-FILE.
       01  EMP-REC.
           05  EMP-ID          PIC X(6).
           05  EMP-HOURS       PIC 9(3).
           05  EMP-GRADE       PIC X(2).
       WORKING-STORAGE SECTION.
       01  WS-EMP-STATUS       PIC XX.
       01  WS-EOF              PIC X VALUE "N".
           88  END-OF-FILE     VALUE "Y".
       01  WS-RUN-DATE         PIC X(8).
       01  WS-EMP-COUNT        PIC 9(5) VALUE 0.
       01  WS-TOTAL-PAY        PIC 9(7)V99 VALUE 0.
       01  PAY-AREA.
           05  PA-HOURS        PIC 9(3).
           05  PA-GRADE        PIC X(2).
           05  PA-GROSS        PIC 9(7)V99.
           05  PA-RC           PIC 9(2).
       PROCEDURE DIVISION.
       0000-MAIN.
           CALL "DATEUTL" USING WS-RUN-DATE
           OPEN INPUT EMP-FILE
           PERFORM 1000-READ-EMP
           PERFORM 2000-PAY-EMP UNTIL END-OF-FILE
           CLOSE EMP-FILE
           GOBACK.
       1000-READ-EMP.
           READ EMP-FILE
               AT END SET END-OF-FILE TO TRUE
           END-READ.
       2000-PAY-EMP.
           MOVE EMP-HOURS TO PA-HOURS
           MOVE EMP-GRADE TO PA-GRADE
           CALL "PAYCALC" USING PAY-AREA
           IF PA-RC = 0
               ADD PA-GROSS TO WS-TOTAL-PAY
               ADD 1 TO WS-EMP-COUNT
           END-IF
           PERFORM 1000-READ-EMP.
