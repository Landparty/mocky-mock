       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSCICS.
      * CICS ACCESS TO THE ACCOUNT KSDS: READ, READ UPDATE + REWRITE,
      * WRITE, DELETE, AND A STARTBR/READNEXT BROWSE
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP                PIC S9(8) COMP.
       01  WS-KEY                 PIC 9(6).
       01  WS-COUNT               PIC 9(4) VALUE 0.
       01  WS-TOTAL               PIC S9(9)V99 VALUE 0.
       01  WS-MSG                 PIC X(40).
       01  ACCT-REC.
           05  AK-ID              PIC 9(6).
           05  AK-NAME            PIC X(20).
           05  AK-BAL             PIC S9(7)V99.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  CA-FUNC            PIC X.
           05  CA-ID              PIC 9(6).
           05  CA-AMOUNT          PIC S9(7)V99.
           05  CA-RESULT          PIC X(2).
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE CA-ID TO WS-KEY
           EVALUATE CA-FUNC
               WHEN 'I'
                   PERFORM 1000-INQUIRE
               WHEN 'U'
                   PERFORM 2000-UPDATE
               WHEN 'A'
                   PERFORM 3000-ADD
               WHEN 'D'
                   PERFORM 4000-DELETE
               WHEN 'B'
                   PERFORM 5000-BROWSE
               WHEN OTHER
                   MOVE 'FX' TO CA-RESULT
           END-EVALUATE
           EXEC CICS RETURN END-EXEC.
       1000-INQUIRE.
           EXEC CICS READ FILE('ACCTKSDS') INTO(ACCT-REC)
               RIDFLD(WS-KEY) RESP(WS-RESP)
           END-EXEC
           EVALUATE WS-RESP
               WHEN DFHRESP(NORMAL)
                   MOVE 'OK' TO CA-RESULT
                   MOVE AK-BAL TO CA-AMOUNT
               WHEN DFHRESP(NOTFND)
                   MOVE 'NF' TO CA-RESULT
               WHEN OTHER
                   MOVE 'ER' TO CA-RESULT
           END-EVALUATE.
       2000-UPDATE.
           EXEC CICS READ FILE('ACCTKSDS') INTO(ACCT-REC)
               RIDFLD(WS-KEY) UPDATE RESP(WS-RESP)
           END-EXEC
           IF WS-RESP = DFHRESP(NORMAL)
               ADD CA-AMOUNT TO AK-BAL
               EXEC CICS REWRITE FILE('ACCTKSDS') FROM(ACCT-REC)
                   RESP(WS-RESP)
               END-EXEC
               MOVE 'OK' TO CA-RESULT
           ELSE
               MOVE 'NF' TO CA-RESULT
           END-IF.
       3000-ADD.
           MOVE CA-ID TO AK-ID
           MOVE 'NEW ACCOUNT' TO AK-NAME
           MOVE CA-AMOUNT TO AK-BAL
           EXEC CICS WRITE FILE('ACCTKSDS') FROM(ACCT-REC)
               RIDFLD(WS-KEY) RESP(WS-RESP)
           END-EXEC
           IF WS-RESP = DFHRESP(DUPREC)
               MOVE 'DP' TO CA-RESULT
           ELSE
               MOVE 'OK' TO CA-RESULT
           END-IF.
       4000-DELETE.
           EXEC CICS DELETE FILE('ACCTKSDS') RIDFLD(WS-KEY)
               RESP(WS-RESP)
           END-EXEC
           IF WS-RESP = DFHRESP(NORMAL)
               MOVE 'OK' TO CA-RESULT
           ELSE
               MOVE 'NF' TO CA-RESULT
           END-IF.
       5000-BROWSE.
           EXEC CICS STARTBR FILE('ACCTKSDS') RIDFLD(WS-KEY)
               GTEQ RESP(WS-RESP)
           END-EXEC
           IF WS-RESP NOT = DFHRESP(NORMAL)
               MOVE 'NF' TO CA-RESULT
           ELSE
               PERFORM UNTIL WS-RESP NOT = DFHRESP(NORMAL)
                       OR WS-COUNT >= 10
                   EXEC CICS READNEXT FILE('ACCTKSDS') INTO(ACCT-REC)
                       RIDFLD(WS-KEY) RESP(WS-RESP)
                   END-EXEC
                   IF WS-RESP = DFHRESP(NORMAL)
                       ADD 1 TO WS-COUNT
                       ADD AK-BAL TO WS-TOTAL
                   END-IF
               END-PERFORM
               EXEC CICS ENDBR FILE('ACCTKSDS') END-EXEC
               MOVE WS-TOTAL TO CA-AMOUNT
               MOVE 'OK' TO CA-RESULT
           END-IF.
