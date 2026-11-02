       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTEXT.
      * STEP 1 OF CUSTJOB: KEEP ACTIVE CUSTOMERS WITH A BALANCE
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-IN  ASSIGN TO CUSTIN
               FILE STATUS IS WS-IN-FS.
           SELECT CUST-OUT ASSIGN TO CUSTOUT
               FILE STATUS IS WS-OUT-FS.
           SELECT RPT-OUT  ASSIGN TO RPTOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-IN.
       01  IN-REC.
           COPY CUSTREC.
       FD  CUST-OUT.
       01  OUT-REC                PIC X(32).
       FD  RPT-OUT.
       01  RPT-LINE               PIC X(60).
       WORKING-STORAGE SECTION.
       01  WS-IN-FS               PIC XX.
       01  WS-OUT-FS              PIC XX.
       01  WS-EOF                 PIC X VALUE 'N'.
       01  WS-READ                PIC 9(5) VALUE 0.
       01  WS-KEPT                PIC 9(5) VALUE 0.
       01  WS-FMT-LINE            PIC X(60).
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT CUST-IN
           OPEN OUTPUT CUST-OUT
           OPEN OUTPUT RPT-OUT
           PERFORM UNTIL WS-EOF = 'Y'
               READ CUST-IN
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM 1000-ONE
               END-READ
           END-PERFORM
           CLOSE CUST-IN
           CLOSE CUST-OUT
           CLOSE RPT-OUT
           DISPLAY 'CUSTEXT READ ' WS-READ ' KEPT ' WS-KEPT
           GOBACK.
       1000-ONE.
           ADD 1 TO WS-READ
           IF CUST-ACTIVE AND CUST-BAL > 0
               ADD 1 TO WS-KEPT
               MOVE IN-REC TO OUT-REC
               WRITE OUT-REC
               CALL 'CUSTFMT' USING IN-REC WS-FMT-LINE
               MOVE WS-FMT-LINE TO RPT-LINE
               WRITE RPT-LINE
           END-IF.
