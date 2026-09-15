       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSONLN.
      *================================================================*
      * Program type: CICS pseudo-conversational online transaction.   *
      * BMS map in/out, DFHCOMMAREA state across RETURN TRANSID, RESP  *
      * handling with DFHRESP, LINK/XCTL to other programs, HANDLE AID.*
      * Untranslated source: EIB fields and DFHCOMMAREA are supplied   *
      * by the CICS translator, not declared here.                     *
      *================================================================*
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP                 PIC S9(8) COMP.
       01  WS-RESP2                PIC S9(8) COMP.
       01  WS-ABSTIME              PIC S9(15) COMP-3.
       01  WS-DATE-OUT             PIC X(10).
       01  WS-TIME-OUT             PIC X(8).
       01  WS-MESSAGE              PIC X(79).
       01  WS-COMMAREA-LEN         PIC S9(4) COMP VALUE 100.
       01  WS-CUST-RECORD.
           05  CUST-ID             PIC X(8).
           05  CUST-NAME           PIC X(30).
           05  CUST-BALANCE        PIC S9(9)V99 COMP-3.
           05  FILLER              PIC X(56).
       01  WS-MAP-AREA.
           05  CUSTIDL             PIC S9(4) COMP.
           05  CUSTIDF             PIC X.
           05  CUSTIDI             PIC X(8).
           05  NAMEL               PIC S9(4) COMP.
           05  NAMEF               PIC X.
           05  NAMEO               PIC X(30).
           05  MSGL                PIC S9(4) COMP.
           05  MSGF                PIC X.
           05  MSGO                PIC X(79).
       01  WS-COMMAREA.
           05  CA-STATE            PIC X.
               88  CA-FIRST-TIME   VALUE ' '.
               88  CA-AWAIT-INPUT  VALUE 'I'.
           05  CA-LAST-CUST        PIC X(8).
           05  FILLER              PIC X(91).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-STATE            PIC X.
           05  LK-LAST-CUST        PIC X(8).
           05  FILLER              PIC X(91).
       PROCEDURE DIVISION.
       0000-MAIN.
           IF EIBCALEN = 0
               MOVE LOW-VALUES TO WS-COMMAREA
               SET CA-FIRST-TIME TO TRUE
               PERFORM 1000-SEND-FRESH-MAP
           ELSE
               MOVE DFHCOMMAREA TO WS-COMMAREA
               PERFORM 2000-PROCESS-INPUT
           END-IF
           EXEC CICS RETURN
               TRANSID('CINQ')
               COMMAREA(WS-COMMAREA)
               LENGTH(WS-COMMAREA-LEN)
           END-EXEC.
       1000-SEND-FRESH-MAP.
           MOVE LOW-VALUES TO WS-MAP-AREA
           MOVE 'ENTER CUSTOMER ID' TO MSGO
           EXEC CICS SEND MAP('CINQMAP') MAPSET('CINQSET')
               FROM(WS-MAP-AREA)
               ERASE
               RESP(WS-RESP)
           END-EXEC
           SET CA-AWAIT-INPUT TO TRUE.
       2000-PROCESS-INPUT.
           EXEC CICS HANDLE AID
               PF3(9000-EXIT-PROGRAM)
               CLEAR(9000-EXIT-PROGRAM)
           END-EXEC
           EXEC CICS RECEIVE MAP('CINQMAP') MAPSET('CINQSET')
               INTO(WS-MAP-AREA)
               RESP(WS-RESP) RESP2(WS-RESP2)
           END-EXEC
           EVALUATE WS-RESP
               WHEN DFHRESP(NORMAL)
                   PERFORM 2100-LOOKUP-CUSTOMER
               WHEN DFHRESP(MAPFAIL)
                   MOVE 'NO DATA ENTERED' TO MSGO
                   PERFORM 2900-SEND-MAP-DATAONLY
               WHEN OTHER
                   PERFORM 9100-ABEND
           END-EVALUATE.
       2100-LOOKUP-CUSTOMER.
           MOVE CUSTIDI TO CUST-ID
           EXEC CICS READ FILE('CUSTMST')
               INTO(WS-CUST-RECORD)
               RIDFLD(CUST-ID)
               KEYLENGTH(8)
               RESP(WS-RESP)
           END-EXEC
           EVALUATE WS-RESP
               WHEN DFHRESP(NORMAL)
                   MOVE CUST-NAME TO NAMEO
                   MOVE CUST-ID TO CA-LAST-CUST
                   EXEC CICS ASKTIME ABSTIME(WS-ABSTIME) END-EXEC
                   EXEC CICS FORMATTIME ABSTIME(WS-ABSTIME)
                       YYYYMMDD(WS-DATE-OUT) DATESEP('-')
                       TIME(WS-TIME-OUT) TIMESEP
                   END-EXEC
                   STRING 'FOUND AT ' DELIMITED BY SIZE
                          WS-TIME-OUT DELIMITED BY SIZE
                          INTO MSGO
                   END-STRING
                   EXEC CICS LINK PROGRAM('CUSTAUDT')
                       COMMAREA(WS-CUST-RECORD)
                       LENGTH(LENGTH OF WS-CUST-RECORD)
                       RESP(WS-RESP)
                   END-EXEC
               WHEN DFHRESP(NOTFND)
                   MOVE 'CUSTOMER NOT FOUND' TO MSGO
               WHEN OTHER
                   PERFORM 9100-ABEND
           END-EVALUATE
           PERFORM 2900-SEND-MAP-DATAONLY.
       2900-SEND-MAP-DATAONLY.
           EXEC CICS SEND MAP('CINQMAP') MAPSET('CINQSET')
               FROM(WS-MAP-AREA)
               DATAONLY
               CURSOR
           END-EXEC.
       9000-EXIT-PROGRAM.
           EXEC CICS XCTL PROGRAM('CMENU')
               RESP(WS-RESP)
           END-EXEC.
       9100-ABEND.
           EXEC CICS SYNCPOINT ROLLBACK END-EXEC
           EXEC CICS ABEND ABCODE('CINQ') END-EXEC.
