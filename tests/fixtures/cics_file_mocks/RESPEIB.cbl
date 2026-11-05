       IDENTIFICATION DIVISION.
       PROGRAM-ID. RESPEIB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC       PIC X(20).
       01  WS-KEY       PIC X(5) VALUE "00001".
       01  WS-RESP      PIC S9(8) COMP.
       01  WS-RESP2     PIC S9(8) COMP.
       01  WS-EIB       PIC X(10) VALUE SPACES.
       01  WS-EIB2      PIC S9(8) COMP VALUE 0.
       01  WS-OWN       PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       READ-PARA.
           EXEC CICS READ FILE('CUST') INTO(WS-REC) RIDFLD(WS-KEY)
                RESP(WS-RESP) RESP2(WS-RESP2)
           END-EXEC
           IF EIBRESP = DFHRESP(NOTFND)
               MOVE "EIB-NOTFND" TO WS-EIB
           ELSE
               MOVE "EIB-OTHER" TO WS-EIB
           END-IF
           MOVE EIBRESP2 TO WS-EIB2
           IF WS-RESP = DFHRESP(NOTFND)
               MOVE "OWN-NOTFND" TO WS-OWN
           ELSE
               MOVE "OWN-OTHER" TO WS-OWN
           END-IF.
