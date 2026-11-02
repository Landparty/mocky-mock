       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSESDS.
      * ESDS: APPEND AUDIT RECORDS (OPEN EXTEND), THEN RE-READ THE LOG
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EVT-FILE ASSIGN TO EVTIN
               FILE STATUS IS WS-EVT-FS.
           SELECT AUDIT-ESDS ASSIGN TO AUDESDS
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-AUD-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  EVT-FILE.
       01  EVT-REC.
           05  EV-USER            PIC X(8).
           05  EV-ACTION          PIC X(10).
       FD  AUDIT-ESDS.
       01  AUD-REC.
           05  AU-SEQ             PIC 9(8).
           05  AU-USER            PIC X(8).
           05  AU-ACTION          PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-EVT-FS              PIC XX.
       01  WS-AUD-FS              PIC XX.
       01  WS-EOF                 PIC X VALUE 'N'.
       01  WS-SEQ                 PIC 9(8) VALUE 0.
       01  WS-WRITTEN             PIC 9(5) VALUE 0.
       01  WS-DELETES             PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT EVT-FILE
           OPEN EXTEND AUDIT-ESDS
           IF WS-AUD-FS = '35'
               DISPLAY 'VSESDS NO AUDIT LOG, CREATING IT'
               OPEN OUTPUT AUDIT-ESDS
           END-IF
           PERFORM UNTIL WS-EOF = 'Y'
               READ EVT-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-SEQ
                       MOVE WS-SEQ TO AU-SEQ
                       MOVE EV-USER TO AU-USER
                       MOVE EV-ACTION TO AU-ACTION
                       WRITE AUD-REC
                       IF WS-AUD-FS = '00'
                           ADD 1 TO WS-WRITTEN
                       ELSE
                           DISPLAY 'VSESDS WRITE FAILED ' WS-AUD-FS
                       END-IF
               END-READ
           END-PERFORM
           CLOSE EVT-FILE AUDIT-ESDS
           OPEN INPUT AUDIT-ESDS
           MOVE 'N' TO WS-EOF
           PERFORM UNTIL WS-EOF = 'Y'
               READ AUDIT-ESDS
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       IF AU-ACTION = 'DELETE'
                           ADD 1 TO WS-DELETES
                       END-IF
               END-READ
           END-PERFORM
           CLOSE AUDIT-ESDS
           DISPLAY 'VSESDS WROTE ' WS-WRITTEN
               ' DELETES IN LOG ' WS-DELETES
           GOBACK.
