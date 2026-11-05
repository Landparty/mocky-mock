       IDENTIFICATION DIVISION.
       PROGRAM-ID. MQOK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  W-HCONN     PIC S9(9) BINARY VALUE 0.
       01  W-HOBJ      PIC S9(9) BINARY VALUE 0.
       01  W-OPTS      PIC S9(9) BINARY VALUE 0.
       01  W-CC        PIC S9(9) BINARY VALUE 99.
       01  W-RC        PIC S9(9) BINARY VALUE 99.
       01  W-OD        PIC X(100).
       01  W-MD        PIC X(100).
       01  W-GMO       PIC X(100).
       01  W-BUFLEN    PIC S9(9) BINARY VALUE 50.
       01  W-DATALEN   PIC S9(9) BINARY VALUE 0.
       01  W-BUF       PIC X(50).
       01  W-MQGET     PIC X(8) VALUE "MQGET".
       01  W-N         PIC 9(4) VALUE 0.
       01  W-MSG       PIC X(20) VALUE SPACES.
       01  W-LAST      PIC X(50) VALUE SPACES.
       PROCEDURE DIVISION.
       OPEN-PARA.
           CALL "MQOPEN" USING W-HCONN W-OD W-OPTS W-HOBJ W-CC W-RC
           IF W-CC = 0 AND W-RC = 0
               MOVE "OPENED" TO W-MSG
           ELSE
               MOVE "OPEN-FAILED" TO W-MSG
           END-IF.
       DYN-GET-PARA.
           CALL W-MQGET USING W-HCONN W-HOBJ W-MD W-GMO W-BUFLEN
                W-BUF W-DATALEN W-CC W-RC
           IF W-CC = 0
               MOVE "GOT" TO W-MSG
           ELSE
               MOVE "NO-MESSAGE" TO W-MSG
           END-IF.
       LOOP-PARA.
           PERFORM UNTIL W-RC = 2033
               CALL "MQGET" USING W-HCONN W-HOBJ W-MD W-GMO W-BUFLEN
                    W-BUF W-DATALEN W-CC W-RC
               IF W-CC = 0
                   ADD 1 TO W-N
                   MOVE W-BUF TO W-LAST
               END-IF
           END-PERFORM.
