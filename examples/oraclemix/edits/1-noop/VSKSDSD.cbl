       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSKSDSD.
      * KSDS DYNAMIC: BROWSE A KEY RANGE FORWARD, LAST RECORD BACKWARD,
      * REVIEWED 2026-11-02
      * AND READ BY ALTERNATE KEY (BRANCH WITH DUPLICATES)
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PARM-FILE ASSIGN TO PARMIN
               FILE STATUS IS WS-PARM-FS.
           SELECT CUST-KSDS ASSIGN TO CUSTKSDS
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CK-ID
               ALTERNATE RECORD KEY IS CK-BRANCH WITH DUPLICATES
               FILE STATUS IS WS-CUST-FS.
           SELECT RPT-FILE ASSIGN TO RPTOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  PARM-FILE.
       01  PARM-REC.
           05  PM-FROM-ID         PIC 9(6).
           05  PM-TO-ID           PIC 9(6).
           05  PM-BRANCH          PIC X(4).
       FD  CUST-KSDS.
       01  CUST-REC.
           05  CK-ID              PIC 9(6).
           05  CK-BRANCH          PIC X(4).
           05  CK-NAME            PIC X(20).
           05  CK-BAL             PIC S9(7)V99.
       FD  RPT-FILE.
       01  RPT-LINE               PIC X(60).
       WORKING-STORAGE SECTION.
       01  WS-PARM-FS             PIC XX.
       01  WS-CUST-FS             PIC XX.
       01  WS-DONE                PIC X VALUE 'N'.
       01  WS-COUNT               PIC 9(5) VALUE 0.
       01  WS-TOTAL               PIC S9(9)V99 VALUE 0.
       01  WS-LINE.
           05  WL-TAG             PIC X(8).
           05  WL-ID              PIC 9(6).
           05  FILLER             PIC X VALUE SPACE.
           05  WL-NAME            PIC X(20).
           05  FILLER             PIC X VALUE SPACE.
           05  WL-BAL             PIC -(7)9.99.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT PARM-FILE CUST-KSDS
           OPEN OUTPUT RPT-FILE
           READ PARM-FILE
               AT END
                   DISPLAY 'VSKSDSD NO PARM'
                   MOVE 8 TO RETURN-CODE
               NOT AT END
                   PERFORM 1000-RANGE
                   PERFORM 2000-LAST
                   PERFORM 3000-BRANCH
           END-READ
           CLOSE PARM-FILE CUST-KSDS RPT-FILE
           DISPLAY 'VSKSDSD RANGE COUNT ' WS-COUNT ' TOTAL ' WS-TOTAL
           GOBACK.
       1000-RANGE.
           MOVE PM-FROM-ID TO CK-ID
           START CUST-KSDS KEY IS NOT LESS THAN CK-ID
               INVALID KEY
                   DISPLAY 'NOTHING FROM ' PM-FROM-ID
                   MOVE 'Y' TO WS-DONE
           END-START
           PERFORM UNTIL WS-DONE = 'Y'
               READ CUST-KSDS NEXT RECORD
                   AT END
                       MOVE 'Y' TO WS-DONE
                   NOT AT END
                       IF CK-ID > PM-TO-ID
                           MOVE 'Y' TO WS-DONE
                       ELSE
                           ADD 1 TO WS-COUNT
                           ADD CK-BAL TO WS-TOTAL
                           MOVE 'RANGE' TO WL-TAG
                           PERFORM 9000-WRITE-LINE
                       END-IF
               END-READ
           END-PERFORM.
       2000-LAST.
           MOVE HIGH-VALUES TO CUST-REC
           MOVE 999999 TO CK-ID
           START CUST-KSDS KEY IS LESS THAN OR EQUAL CK-ID
               INVALID KEY
                   DISPLAY 'FILE EMPTY'
               NOT INVALID KEY
                   READ CUST-KSDS PREVIOUS RECORD
                       AT END DISPLAY 'FILE EMPTY'
                       NOT AT END
                           MOVE 'LAST' TO WL-TAG
                           PERFORM 9000-WRITE-LINE
                   END-READ
           END-START.
       3000-BRANCH.
           MOVE PM-BRANCH TO CK-BRANCH
           READ CUST-KSDS KEY IS CK-BRANCH
               INVALID KEY
                   DISPLAY 'NO CUSTOMER IN BRANCH ' PM-BRANCH
               NOT INVALID KEY
                   MOVE 'BRANCH' TO WL-TAG
                   PERFORM 9000-WRITE-LINE
                   IF WS-CUST-FS = '02'
                       DISPLAY 'BRANCH ' PM-BRANCH ' HAS MORE CUSTOMERS'
                   END-IF
           END-READ.
       9000-WRITE-LINE.
           MOVE CK-ID TO WL-ID
           MOVE CK-NAME TO WL-NAME
           MOVE CK-BAL TO WL-BAL
           WRITE RPT-LINE FROM WS-LINE.
