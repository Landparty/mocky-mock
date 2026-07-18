       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEPTIMSM.
      *****************************************************************
      * DEPOSIT TRANSACTION - IMS MPP (MESSAGE PROCESSING PROGRAM)  *
      * DESCRIPTION: Receives deposit/withdrawal requests from       *
      *   IMS Connect (TCP/IP gateway), validates the CIF and       *
      *   amount, inserts a TRNSEG child under CUSTSEG in CUSTDB,  *
      *   and returns a reply message to the caller.                *
      * INPUT:  IMS message queue (via IMS Connect TCP/IP gateway)  *
      *         MSG-CIF-NUMBER + MSG-ACCT-NUMBER + MSG-AMOUNT-CHAR  *
      *         + MSG-TRAN-TYPE (DP=deposit, WD=withdrawal)         *
      * OUTPUT: DEPT-OUTPUT-MSG reply (RC 00/04/08/12)             *
      *         CUSTDB TRNSEG child segment inserted on success     *
      * ENTRY:  DLITCBL (IMS standard COBOL PCB entry point)       *
      * PCBs:   IOPCB (message queue) + CUST-PCB (CUSTDB)          *
      * PSB:    DEPTPSB                                             *
      * TRAN:   DEPTTRAN (defined in IMS system gen)               *
      * IMS TYPE: MPP (Message Processing Program)                 *
      *****************************************************************

       ENVIRONMENT DIVISION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY WSCOMMON.
           COPY ERRORCD.
           COPY IMSPCB.
           COPY TRNSEG.

       01  WS-MSG-FLAGS.
           05  WS-NO-MORE-MSGS      PIC X(01) VALUE 'N'.
               88  NO-MORE-MSGS     VALUE 'Y'.
               88  MORE-MSGS        VALUE 'N'.
           05  WS-TRAN-ERROR        PIC X(01) VALUE 'N'.
               88  TRAN-ERROR-FOUND VALUE 'Y'.
               88  TRAN-OK          VALUE 'N'.

       01  WS-EDIT-WORK.
           05  WS-AMOUNT-WORK       PIC S9(11)V99.
           05  WS-AMOUNT-DISP       PIC ZZZ,ZZZ,ZZZ.99.

       01  WS-REPLY-LEN             PIC S9(04) COMP VALUE +64.

       LINKAGE SECTION.
       01  IOPCB-LNK.
           05  IOPCB-LTERM          PIC X(08).
           05  IOPCB-FILL1          PIC X(02).
           05  IOPCB-STATUS         PIC X(02).
               88  IOPCB-SUCCESS    VALUE '  '.
               88  IOPCB-NO-MSG     VALUE 'QC'.
           05  IOPCB-DATE           PIC S9(07) COMP-3.
           05  IOPCB-TIME           PIC S9(06) COMP-3.
           05  IOPCB-MSG-LEN        PIC S9(05) COMP.
           05  IOPCB-MOD-NAME       PIC X(08).
           05  IOPCB-USERID         PIC X(08).
           05  IOPCB-TRAN-CODE      PIC X(08).

       01  CUST-PCB-LNK.
           05  CUST-DBD-NAME        PIC X(08).
           05  CUST-SEG-LEVEL       PIC X(02).
           05  CUST-STATUS          PIC X(02).
               88  CUST-PCB-OK      VALUE '  '.
               88  CUST-PCB-NF      VALUE 'GE'.
           05  CUST-PROC-OPTIONS    PIC X(04).
           05  CUST-RESERVED        PIC S9(05) COMP.
           05  CUST-SEG-NAME        PIC X(08).
           05  CUST-KEY-LEN         PIC S9(05) COMP.
           05  CUST-NUM-SENS-SEGS   PIC S9(05) COMP.
           05  CUST-KEY-FEEDBACK    PIC X(30).

       PROCEDURE DIVISION.
       ENTRY 'DLITCBL' USING IOPCB-LNK
                             CUST-PCB-LNK.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS-MESSAGES
               UNTIL NO-MORE-MSGS
           PERFORM 3000-FINALIZE
           GOBACK.

       1000-INITIALIZE.
           DISPLAY 'DEPTIMSM: MPP DEPOSIT TRANSACTION STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR  DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-MONTH DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-DAY   DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING
           SET MORE-MSGS TO TRUE.

       2000-PROCESS-MESSAGES.
           PERFORM 2100-GET-MSG
           IF NOT NO-MORE-MSGS
               MOVE 'N' TO WS-TRAN-ERROR
               ADD 1 TO WS-RECS-READ
               PERFORM 2200-VALIDATE-INPUT
               IF TRAN-OK
                   PERFORM 2300-GET-CUSTOMER
               END-IF
               IF TRAN-OK
                   PERFORM 2400-INSERT-TRNSEG
               END-IF
               PERFORM 2500-SEND-REPLY
           END-IF.

       2100-GET-MSG.
      *    GU ON IOPCB RETRIEVES NEXT MESSAGE FROM IMS CONNECT QUEUE
           CALL 'CBLTDLI' USING DLI-GU
                                IOPCB-LNK
                                DEPT-INPUT-MSG
           EVALUATE IOPCB-STATUS
               WHEN '  '
                   CONTINUE
               WHEN 'QC'
                   SET NO-MORE-MSGS TO TRUE
               WHEN OTHER
                   DISPLAY 'DEPTIMSM: IOPCB GU ERROR STATUS='
                           IOPCB-STATUS
                   SET NO-MORE-MSGS TO TRUE
           END-EVALUATE.

       2200-VALIDATE-INPUT.
           IF MSG-CIF-NUMBER = SPACES OR LOW-VALUES
               MOVE '08'                      TO REPLY-RC
               MOVE 'CIF NUMBER REQUIRED'     TO REPLY-TEXT
               SET TRAN-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           IF MSG-TRAN-TYPE NOT = 'DP' AND NOT = 'WD'
               MOVE '08'                      TO REPLY-RC
               MOVE 'TRAN TYPE MUST BE DP OR WD' TO REPLY-TEXT
               SET TRAN-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           IF FUNCTION TEST-NUMVAL(MSG-AMOUNT-CHAR) NOT = ZERO
               MOVE '08'                      TO REPLY-RC
               MOVE 'AMOUNT IS NOT NUMERIC'   TO REPLY-TEXT
               SET TRAN-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           COMPUTE WS-AMOUNT-WORK =
               FUNCTION NUMVAL(MSG-AMOUNT-CHAR)
           IF WS-AMOUNT-WORK <= ZERO
               MOVE '08'                      TO REPLY-RC
               MOVE 'AMOUNT MUST BE GREATER THAN ZERO' TO REPLY-TEXT
               SET TRAN-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
           END-IF.

       2300-GET-CUSTOMER.
      *    GU ON CUST-PCB CONFIRMS CUSTOMER EXISTS AND SETS POSITION
      *    FOR THE SUBSEQUENT ISRT OF THE TRNSEG CHILD SEGMENT
           MOVE MSG-CIF-NUMBER TO SSA-CUST-KEY-VALUE
           CALL 'CBLTDLI' USING DLI-GU
                                CUST-PCB-LNK
                                IMS-IO-AREA
                                SSA-CUSTOMER
           EVALUATE CUST-STATUS
               WHEN '  '
                   CONTINUE
               WHEN 'GE'
                   MOVE '04'                  TO REPLY-RC
                   STRING 'CUSTOMER NOT FOUND: ' DELIMITED BY SIZE
                          MSG-CIF-NUMBER       DELIMITED BY SIZE
                          INTO REPLY-TEXT
                   END-STRING
                   SET TRAN-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-CUST-NOT-FOUND
               WHEN OTHER
                   MOVE '12'                  TO REPLY-RC
                   MOVE 'DB ERROR ON CUSTOMER LOOKUP' TO REPLY-TEXT
                   SET TRAN-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-DB-ERRORS
                   DISPLAY 'DEPTIMSM: CUSTDB GU ERROR STATUS='
                           CUST-STATUS
                           ' CIF=' MSG-CIF-NUMBER
           END-EVALUATE.

       2400-INSERT-TRNSEG.
      *    ISRT WITH QUALIFIED SSA INSERTS TRNSEG UNDER THE CUSTSEG
      *    FOUND ABOVE. PATH: CUSTSEG(CUSTID=cif) -> TRNSEG
           MOVE SPACES                TO TRNSEG-IO
           MOVE MSG-CIF-NUMBER        TO TRAN-CIF-NUMBER
           MOVE MSG-ACCT-NUMBER       TO TRAN-ACCT-NUMBER
           MOVE WS-AMOUNT-WORK        TO TRAN-AMOUNT
           MOVE MSG-TRAN-TYPE         TO TRAN-TYPE
           MOVE WS-BUSINESS-DATE      TO TRAN-DATE
           MOVE 'IMSC'                TO TRAN-CHANNEL
           MOVE 'P'                   TO TRAN-STATUS
           MOVE FUNCTION CURRENT-DATE TO TRAN-TIMESTAMP

           CALL 'CBLTDLI' USING DLI-ISRT
                                CUST-PCB-LNK
                                TRNSEG-IO
                                SSA-CUSTOMER
                                SSA-UNQUAL-TRAN
           EVALUATE CUST-STATUS
               WHEN '  '
                   ADD 1 TO WS-TRNS-INSERTED
                   MOVE '00'          TO REPLY-RC
                   MOVE WS-AMOUNT-WORK TO WS-AMOUNT-DISP
                   STRING MSG-TRAN-TYPE          DELIMITED BY SIZE
                          ' POSTED: '            DELIMITED BY SIZE
                          WS-AMOUNT-DISP         DELIMITED BY SIZE
                          ' ACCT=' MSG-ACCT-NUMBER DELIMITED BY SIZE
                          INTO REPLY-TEXT
                   END-STRING
               WHEN OTHER
                   MOVE '12'          TO REPLY-RC
                   MOVE 'DB ERROR ON TRNSEG INSERT' TO REPLY-TEXT
                   SET TRAN-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-DB-ERRORS
                   DISPLAY 'DEPTIMSM: TRNSEG ISRT ERROR STATUS='
                           CUST-STATUS
                           ' CIF=' MSG-CIF-NUMBER
           END-EVALUATE.

       2500-SEND-REPLY.
      *    ISRT ON IOPCB SENDS REPLY BACK THROUGH IMS CONNECT
           MOVE WS-REPLY-LEN TO REPLY-LL
           MOVE LOW-VALUES   TO REPLY-ZZ
           CALL 'CBLTDLI' USING DLI-ISRT
                                IOPCB-LNK
                                DEPT-OUTPUT-MSG
           IF NOT IOPCB-SUCCESS
               DISPLAY 'DEPTIMSM: IOPCB REPLY ISRT ERROR STATUS='
                       IOPCB-STATUS
           END-IF.

       3000-FINALIZE.
           DISPLAY 'DEPTIMSM: MPP DEPOSIT TRANSACTION COMPLETE'
           DISPLAY 'MESSAGES RECEIVED:   ' WS-RECS-READ
           DISPLAY 'SEGMENTS INSERTED:   ' WS-TRNS-INSERTED
           DISPLAY 'CUSTOMER NOT FOUND:  ' WS-CUST-NOT-FOUND
           DISPLAY 'INVALID INPUT:       ' WS-INVALID-INPUT
           DISPLAY 'DATABASE ERRORS:     ' WS-DB-ERRORS.
