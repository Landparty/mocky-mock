       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTINQ.
      * CICS CUSTOMER INQUIRY, TRANSACTION CINQ (PSEUDO-CONVERSATIONAL)
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COMMAREA.
           05  CA-STATE           PIC X.
           05  CA-CUST-ID         PIC 9(6).
       01  WS-VAL-AREA.
           05  VA-CUST-ID         PIC 9(6).
           05  VA-RESULT          PIC X(2).
       01  WS-RESP                PIC S9(8) COMP.
       01  WS-CUST.
           COPY CUSTREC.
       COPY CUSTSET.
       LINKAGE SECTION.
       01  DFHCOMMAREA            PIC X(7).
       PROCEDURE DIVISION.
       0000-MAIN.
           IF EIBCALEN = 0
               PERFORM 1000-FIRST-TIME
           ELSE
               MOVE DFHCOMMAREA TO WS-COMMAREA
               IF EIBAID = X'F3'
                   EXEC CICS XCTL PROGRAM('CUSTMENU') END-EXEC
               ELSE
                   PERFORM 2000-INQUIRE
               END-IF
           END-IF
           EXEC CICS RETURN TRANSID('CINQ')
               COMMAREA(WS-COMMAREA) LENGTH(7)
           END-EXEC
           GOBACK.
       1000-FIRST-TIME.
           MOVE LOW-VALUES TO CUSTMAPO
           MOVE 'ENTER A CUSTOMER ID' TO MSGO
           EXEC CICS SEND MAP('CUSTMAP') MAPSET('CUSTSET')
               FROM(CUSTMAPO) ERASE
           END-EXEC
           MOVE '1' TO CA-STATE.
       2000-INQUIRE.
           EXEC CICS RECEIVE MAP('CUSTMAP') MAPSET('CUSTSET')
               INTO(CUSTMAPI) RESP(WS-RESP)
           END-EXEC
           MOVE CUSTIDI TO VA-CUST-ID
           EXEC CICS LINK PROGRAM('CUSTVAL')
               COMMAREA(WS-VAL-AREA) LENGTH(8)
           END-EXEC
           MOVE LOW-VALUES TO CUSTMAPO
           IF VA-RESULT = 'OK'
               MOVE VA-CUST-ID TO CUST-ID CA-CUST-ID
               EXEC CICS READ FILE('CUSTFIL') INTO(WS-CUST)
                   RIDFLD(CUST-ID) RESP(WS-RESP)
               END-EXEC
               IF WS-RESP = DFHRESP(NORMAL)
                   MOVE CUST-NAME TO CUSTNMO
                   MOVE 'FOUND' TO MSGO
               ELSE
                   MOVE 'NOT FOUND' TO MSGO
               END-IF
           ELSE
               MOVE 'INVALID ID' TO MSGO
           END-IF
           EXEC CICS SEND MAP('CUSTMAP') MAPSET('CUSTSET')
               FROM(CUSTMAPO) DATAONLY
           END-EXEC.
