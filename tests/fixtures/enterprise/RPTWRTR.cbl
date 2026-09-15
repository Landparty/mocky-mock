       IDENTIFICATION DIVISION.
       PROGRAM-ID. RPTWRTR.
      *================================================================*
      * Program type: Report Writer batch report.                      *
      * RD with CONTROLS and PAGE LIMIT, every report-group type       *
      * (RH PH CH DE CF PF RF), SUM with UPON, LINE/COLUMN/SOURCE/    *
      * NEXT GROUP, USE BEFORE REPORTING declaratives,                 *
      * INITIATE / GENERATE / TERMINATE.                               *
      *================================================================*
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SALES-FILE ASSIGN TO SALESIN
               FILE STATUS IS WS-SALES-STATUS.
           SELECT REPORT-FILE ASSIGN TO RPTOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  SALES-FILE
           RECORDING MODE IS F
           RECORD CONTAINS 60 CHARACTERS.
       01  SALES-REC.
           05  SR-REGION           PIC X(4).
           05  SR-BRANCH           PIC X(6).
           05  SR-REP              PIC X(20).
           05  SR-AMOUNT           PIC S9(7)V99 COMP-3.
           05  SR-DATE             PIC 9(8).
           05  FILLER              PIC X(17).
       FD  REPORT-FILE
           REPORT IS SALES-REPORT.
       WORKING-STORAGE SECTION.
       01  WS-SALES-STATUS         PIC XX.
       01  WS-EOF                  PIC X VALUE 'N'.
           88  END-OF-SALES        VALUE 'Y'.
       01  WS-RUN-DATE             PIC 9(8).
       01  WS-REGION-NAME          PIC X(20).
       REPORT SECTION.
       RD  SALES-REPORT
           CONTROLS ARE FINAL SR-REGION SR-BRANCH
           PAGE LIMIT IS 60 LINES
           HEADING 1
           FIRST DETAIL 6
           LAST DETAIL 54
           FOOTING 58.
       01  TYPE IS REPORT HEADING.
           05  LINE 1.
               10  COLUMN 30       PIC X(24)
                   VALUE 'REGIONAL SALES SUMMARY'.
       01  TYPE IS PAGE HEADING.
           05  LINE 3.
               10  COLUMN 1        PIC X(10) VALUE 'RUN DATE: '.
               10  COLUMN 11       PIC 9999/99/99 SOURCE WS-RUN-DATE.
               10  COLUMN 70       PIC X(5) VALUE 'PAGE '.
               10  COLUMN 75       PIC Z9 SOURCE PAGE-COUNTER.
           05  LINE 5.
               10  COLUMN 1        PIC X(6) VALUE 'REGION'.
               10  COLUMN 10       PIC X(6) VALUE 'BRANCH'.
               10  COLUMN 20       PIC X(3) VALUE 'REP'.
               10  COLUMN 45       PIC X(6) VALUE 'AMOUNT'.
       01  REGION-HEAD TYPE IS CONTROL HEADING SR-REGION
           NEXT GROUP PLUS 1.
           05  LINE PLUS 2.
               10  COLUMN 1        PIC X(4) SOURCE SR-REGION.
               10  COLUMN 6        PIC X(20) SOURCE WS-REGION-NAME.
       01  DETAIL-LINE TYPE IS DETAIL.
           05  LINE PLUS 1.
               10  COLUMN 10       PIC X(6) SOURCE SR-BRANCH
                   GROUP INDICATE.
               10  COLUMN 20       PIC X(20) SOURCE SR-REP.
               10  COLUMN 45       PIC Z(6)9.99- SOURCE SR-AMOUNT.
       01  BRANCH-FOOT TYPE IS CONTROL FOOTING SR-BRANCH.
           05  LINE PLUS 1.
               10  COLUMN 20       PIC X(13) VALUE 'BRANCH TOTAL:'.
               10  BRANCH-TOTAL    COLUMN 45 PIC Z(7)9.99-
                   SUM SR-AMOUNT.
       01  REGION-FOOT TYPE IS CONTROL FOOTING SR-REGION
           NEXT GROUP NEXT PAGE.
           05  LINE PLUS 1.
               10  COLUMN 20       PIC X(13) VALUE 'REGION TOTAL:'.
               10  REGION-TOTAL    COLUMN 45 PIC Z(8)9.99-
                   SUM BRANCH-TOTAL.
       01  TYPE IS CONTROL FOOTING FINAL.
           05  LINE PLUS 2.
               10  COLUMN 20       PIC X(12) VALUE 'GRAND TOTAL:'.
               10  COLUMN 44       PIC Z(9)9.99-
                   SUM REGION-TOTAL.
       01  TYPE IS PAGE FOOTING.
           05  LINE 58.
               10  COLUMN 30       PIC X(12) VALUE 'CONFIDENTIAL'.
       01  TYPE IS REPORT FOOTING.
           05  LINE PLUS 1.
               10  COLUMN 30       PIC X(13) VALUE 'END OF REPORT'.
       PROCEDURE DIVISION.
       DECLARATIVES.
       REGION-NAME-SECTION SECTION.
           USE BEFORE REPORTING REGION-HEAD.
       REGION-NAME-PARA.
           EVALUATE SR-REGION
               WHEN 'NE  ' MOVE 'NORTH EAST' TO WS-REGION-NAME
               WHEN 'SW  ' MOVE 'SOUTH WEST' TO WS-REGION-NAME
               WHEN OTHER  MOVE 'OTHER' TO WS-REGION-NAME
           END-EVALUATE.
       END DECLARATIVES.
       MAIN-SECTION SECTION.
       0000-MAIN.
           ACCEPT WS-RUN-DATE FROM DATE YYYYMMDD
           OPEN INPUT SALES-FILE OUTPUT REPORT-FILE
           INITIATE SALES-REPORT
           READ SALES-FILE
               AT END SET END-OF-SALES TO TRUE
           END-READ
           PERFORM UNTIL END-OF-SALES
               GENERATE DETAIL-LINE
               READ SALES-FILE
                   AT END SET END-OF-SALES TO TRUE
               END-READ
           END-PERFORM
           TERMINATE SALES-REPORT
           CLOSE SALES-FILE REPORT-FILE
           STOP RUN.
