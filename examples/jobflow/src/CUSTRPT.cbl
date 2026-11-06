       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTRPT.
      * Step 3 of CUSTJOB: one report line per customer, then a total.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-IN ASSIGN TO RPTIN.
           SELECT RPT-OUT ASSIGN TO RPTOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  RPT-IN.
       01  RPT-IN-REC.
           05  RI-ID              PIC 9(5).
           05  RI-NAME            PIC X(10).
           05  RI-BALANCE         PIC 9(5).
       FD  RPT-OUT.
       01  RPT-LINE               PIC X(40).
       WORKING-STORAGE SECTION.
       01  WS-EOF                 PIC X VALUE "N".
       01  WS-TOTAL               PIC 9(7) VALUE 0.
       01  WS-DETAIL.
           05  WD-ID              PIC 9(5).
           05  FILLER             PIC X VALUE SPACE.
           05  WD-NAME            PIC X(10).
           05  FILLER             PIC X VALUE SPACE.
           05  WD-BALANCE         PIC ZZ,ZZ9.
           05  FILLER             PIC X(17) VALUE SPACES.
       01  WS-TOTAL-LINE.
           05  FILLER             PIC X(6) VALUE "TOTAL ".
           05  WT-TOTAL           PIC Z,ZZZ,ZZ9.
           05  FILLER             PIC X(25) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT RPT-IN OUTPUT RPT-OUT
           PERFORM UNTIL WS-EOF = "Y"
               READ RPT-IN
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END PERFORM DETAIL-PARA
               END-READ
           END-PERFORM
           MOVE WS-TOTAL TO WT-TOTAL
           WRITE RPT-LINE FROM WS-TOTAL-LINE
           CLOSE RPT-IN RPT-OUT
           GOBACK.
       DETAIL-PARA.
           MOVE RI-ID TO WD-ID
           MOVE RI-NAME TO WD-NAME
           MOVE RI-BALANCE TO WD-BALANCE
           ADD RI-BALANCE TO WS-TOTAL
           WRITE RPT-LINE FROM WS-DETAIL.
