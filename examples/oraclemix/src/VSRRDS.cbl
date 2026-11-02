       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSRRDS.
      * RRDS: SLOT TABLE BY RELATIVE RECORD NUMBER (RANDOM READ/WRITE),
      * THEN A SEQUENTIAL SCAN FROM SLOT 10
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT REQ-FILE ASSIGN TO REQIN
               FILE STATUS IS WS-REQ-FS.
           SELECT SLOT-RRDS ASSIGN TO SLOTRRDS
               ORGANIZATION IS RELATIVE
               ACCESS MODE IS DYNAMIC
               RELATIVE KEY IS WS-SLOT
               FILE STATUS IS WS-SLOT-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  REQ-FILE.
       01  REQ-REC.
           05  RQ-SLOT            PIC 9(4).
           05  RQ-OWNER           PIC X(10).
       FD  SLOT-RRDS.
       01  SLOT-REC.
           05  SL-OWNER           PIC X(10).
           05  SL-USES            PIC 9(5).
       WORKING-STORAGE SECTION.
       01  WS-REQ-FS              PIC XX.
       01  WS-SLOT-FS             PIC XX.
       01  WS-SLOT                PIC 9(4).
       01  WS-EOF                 PIC X VALUE 'N'.
       01  WS-NEW                 PIC 9(5) VALUE 0.
       01  WS-TAKEN               PIC 9(5) VALUE 0.
       01  WS-USED                PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT REQ-FILE
           OPEN I-O SLOT-RRDS
           PERFORM UNTIL WS-EOF = 'Y'
               READ REQ-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM 1000-CLAIM
               END-READ
           END-PERFORM
           MOVE 10 TO WS-SLOT
           MOVE 'N' TO WS-EOF
           START SLOT-RRDS KEY IS NOT LESS THAN WS-SLOT
               INVALID KEY MOVE 'Y' TO WS-EOF
           END-START
           PERFORM UNTIL WS-EOF = 'Y'
               READ SLOT-RRDS NEXT
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END ADD SL-USES TO WS-USED
               END-READ
           END-PERFORM
           CLOSE REQ-FILE SLOT-RRDS
           DISPLAY 'VSRRDS NEW ' WS-NEW ' TAKEN ' WS-TAKEN
               ' USES FROM 10 ' WS-USED
           GOBACK.
       1000-CLAIM.
           MOVE RQ-SLOT TO WS-SLOT
           READ SLOT-RRDS
               INVALID KEY
                   MOVE RQ-OWNER TO SL-OWNER
                   MOVE 1 TO SL-USES
                   WRITE SLOT-REC
                       INVALID KEY
                           DISPLAY 'SLOT WRITE FAILED ' WS-SLOT-FS
                   END-WRITE
                   ADD 1 TO WS-NEW
               NOT INVALID KEY
                   IF SL-OWNER = RQ-OWNER
                       ADD 1 TO SL-USES
                       REWRITE SLOT-REC
                   ELSE
                       DISPLAY 'SLOT ' RQ-SLOT ' TAKEN BY ' SL-OWNER
                       ADD 1 TO WS-TAKEN
                   END-IF
           END-READ.
