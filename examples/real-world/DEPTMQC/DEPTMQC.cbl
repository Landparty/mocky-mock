       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEPTMQC.
      *****************************************************************
      * DEPOSIT MQ CONSUMER - IBM MQ BATCH MESSAGE CONSUMER          *
      * DESCRIPTION: Drains BANK.DEPOSIT.QUEUE on queue manager CSQ1 *
      *   using MQGET in a no-wait loop. Each 74-byte payload is     *
      *   validated and posted to DB2 BANK.TRANSACTION_HIST.         *
      *   MQCMIT and DB2 COMMIT are issued together every            *
      *   WS-COMMIT-FREQ messages so the two units of work stay in   *
      *   sync; if either commit fails the current batch rolls back. *
      * INPUT:  BANK.DEPOSIT.QUEUE on QM CSQ1 (MQ messages)         *
      *         Produced by DEPTMQP or any upstream MQ publisher     *
      * OUTPUT: DB2 BANK.TRANSACTION_HIST - one row per message      *
      *         MQCRPT - processing report                           *
      * CALLS:  MQCONN, MQOPEN, MQGET, MQCMIT, MQBACK,             *
      *         MQCLOSE, MQDISC                                      *
      * DB2 PLAN: DEPTPLAN                                           *
      * STEPLIB REQUIRES: MQ.V9R1M0.SCSQLOAD (MQ load library)     *
      * FREQUENCY: On-demand (submitted via DEPTMQCJ.jcl)           *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MQCRPT  ASSIGN TO MQCRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  MQCRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD               PIC X(133).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

           COPY WSCOMMON.
           COPY ERRORCD.
           COPY MQMSG.

       01  WS-MQ-FLAGS.
           05  WS-MQ-CONNECTED      PIC X(01) VALUE 'N'.
               88  MQ-CONNECTED     VALUE 'Y'.
               88  MQ-NOT-CONNECTED VALUE 'N'.
           05  WS-MQ-OPEN           PIC X(01) VALUE 'N'.
               88  MQ-OPEN          VALUE 'Y'.
               88  MQ-NOT-OPEN      VALUE 'N'.
           05  WS-NO-MORE-MSGS      PIC X(01) VALUE 'N'.
               88  NO-MORE-MSGS     VALUE 'Y'.
               88  MORE-MSGS        VALUE 'N'.

       01  WS-MSG-ERROR             PIC X(01) VALUE 'N'.
           88  MSG-ERROR-FOUND      VALUE 'Y'.
           88  MSG-OK               VALUE 'N'.

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES FOR BANK.TRANSACTION_HIST INSERT
      *-----------------------------------------------------------------
       01  WS-TRAN-HV.
           05  HV-TRAN-ID           PIC X(16).
           05  HV-ACCT-NUMBER       PIC X(12).
           05  HV-DR-CR             PIC X(02).
           05  HV-TRAN-CODE         PIC X(04).
           05  HV-AMOUNT            PIC S9(13)V99 COMP-3.
           05  HV-TRAN-DATE         PIC X(10).
           05  HV-TRAN-DESC         PIC X(30).

       01  WS-TRAN-SEED             PIC 9(16) COMP VALUE ZERO.

       01  WS-COUNTERS.
           05  WS-MSGS-READ         PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-ROWS-INSERTED     PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-INVALID-PAYLOAD   PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-MQ-ERRORS         PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-DB2-ERRORS        PIC 9(05) COMP-3 VALUE ZERO.

       01  WS-RC-DISP               PIC -(9)9.
       01  WS-AMOUNT-DISP           PIC ZZZ,ZZZ,ZZZ.99.

       01  WS-HDR.
           05  FILLER PIC X(17) VALUE 'CIF              '.
           05  FILLER PIC X(15) VALUE 'ACCOUNT        '.
           05  FILLER PIC X(05) VALUE 'TYPE '.
           05  FILLER PIC X(20) VALUE '              AMOUNT'.
           05  FILLER PIC X(12) VALUE '  STATUS      '.

       01  WS-DETAIL.
           05  WS-DET-CIF           PIC X(10).
           05  FILLER               PIC X(07) VALUE SPACES.
           05  WS-DET-ACCT          PIC X(12).
           05  FILLER               PIC X(03) VALUE SPACES.
           05  WS-DET-TYPE          PIC X(02).
           05  FILLER               PIC X(03) VALUE SPACES.
           05  WS-DET-AMOUNT        PIC ZZZ,ZZZ,ZZZ.99.
           05  FILLER               PIC X(03) VALUE SPACES.
           05  WS-DET-STATUS        PIC X(14).

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           IF NOT MQ-CONNECTED
               PERFORM 3000-FINALIZE
               STOP RUN
           END-IF
           PERFORM 2000-CONSUME-MESSAGES
               UNTIL NO-MORE-MSGS
           PERFORM 2900-FINAL-COMMIT
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'DEPTMQC: MQ DEPOSIT CONSUMER STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR  DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-MONTH DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-DAY   DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING
           OPEN OUTPUT MQCRPT
           WRITE RPT-RECORD FROM WS-HDR
           SET MORE-MSGS TO TRUE
           PERFORM 1100-MQ-CONNECT
           IF MQ-CONNECTED
               PERFORM 1200-MQ-OPEN
           END-IF.

       1100-MQ-CONNECT.
           CALL 'MQCONN' USING MQ-QMGR-NAME
                               MQ-HCONN
                               MQ-COMP-CODE
                               MQ-REASON-CODE
           IF MQ-COMP-CODE = MQCC-OK
               SET MQ-CONNECTED TO TRUE
               DISPLAY 'DEPTMQC: CONNECTED TO QM ' MQ-QMGR-NAME
           ELSE
               MOVE MQ-COMP-CODE   TO WS-RC-DISP
               DISPLAY 'DEPTMQC: MQCONN FAILED CC=' WS-RC-DISP
               MOVE MQ-REASON-CODE TO WS-RC-DISP
               DISPLAY 'DEPTMQC: MQCONN REASON='    WS-RC-DISP
               ADD 1 TO WS-MQ-ERRORS
           END-IF.

       1200-MQ-OPEN.
      *    MQOO-INPUT-SHARED (8) + MQOO-FAIL-IF-QUIESCE (32) = 40.
      *    INPUT-SHARED ALLOWS OTHER CONSUMERS TO ALSO READ THE QUEUE
      *    CONCURRENTLY IF NEEDED FOR PARALLEL BATCH PROCESSING.
           MOVE MQ-QUEUE-NAME TO MQOD-OBJECTNAME
           COMPUTE MQ-OPEN-OPTIONS =
               MQOO-INPUT-SHARED + MQOO-FAIL-IF-QUIESCE
           CALL 'MQOPEN' USING MQ-HCONN
                               MQOD
                               MQ-OPEN-OPTIONS
                               MQ-HOBJ
                               MQ-COMP-CODE
                               MQ-REASON-CODE
           IF MQ-COMP-CODE = MQCC-OK
               SET MQ-OPEN TO TRUE
               DISPLAY 'DEPTMQC: OPENED QUEUE ' MQ-QUEUE-NAME
           ELSE
               MOVE MQ-COMP-CODE   TO WS-RC-DISP
               DISPLAY 'DEPTMQC: MQOPEN FAILED CC=' WS-RC-DISP
               MOVE MQ-REASON-CODE TO WS-RC-DISP
               DISPLAY 'DEPTMQC: MQOPEN REASON='    WS-RC-DISP
               ADD 1 TO WS-MQ-ERRORS
           END-IF.

       2000-CONSUME-MESSAGES.
           MOVE 'N' TO WS-MSG-ERROR
           PERFORM 2100-MQGET
           IF NOT NO-MORE-MSGS
               ADD 1 TO WS-MSGS-READ
               PERFORM 2200-VALIDATE-PAYLOAD
               IF MSG-OK
                   PERFORM 2300-DB2-INSERT
               END-IF
               PERFORM 2400-WRITE-DETAIL
               PERFORM 2500-PERIODIC-COMMIT
           END-IF.

       2100-MQGET.
      *    MQGET WITH MQGMO-SYNCPOINT (4) + MQGMO-NO-WAIT (0) = 4.
      *    NO-WAIT MEANS MQGET RETURNS IMMEDIATELY IF THE QUEUE IS EMPTY
      *    (MQRC-NO-MSG-AVAIL = 2033), ENDING THE BATCH CLEANLY.
      *    MQ-DATA-LEN RECEIVES THE ACTUAL BYTE LENGTH OF THE MESSAGE;
      *    MQ-BUFFER-LEN CAPS THE READ AT THE PAYLOAD SIZE (74 BYTES).
           MOVE LOW-VALUES  TO MQMD
           MOVE 'MD  '      TO MQMD-STRUCID
           MOVE +1          TO MQMD-VERSION
           MOVE MQ-BUFFER-LEN TO MQ-DATA-LEN
           CALL 'MQGET' USING MQ-HCONN
                              MQ-HOBJ
                              MQMD
                              MQGMO
                              MQ-BUFFER-LEN
                              DEPT-MQ-PAYLOAD
                              MQ-DATA-LEN
                              MQ-COMP-CODE
                              MQ-REASON-CODE
           EVALUATE TRUE
               WHEN MQ-COMP-CODE = MQCC-OK
                   CONTINUE
               WHEN MQ-REASON-CODE = MQRC-NO-MSG-AVAIL
                   SET NO-MORE-MSGS TO TRUE
               WHEN OTHER
                   MOVE MQ-COMP-CODE   TO WS-RC-DISP
                   DISPLAY 'DEPTMQC: MQGET FAILED CC='  WS-RC-DISP
                   MOVE MQ-REASON-CODE TO WS-RC-DISP
                   DISPLAY 'DEPTMQC: MQGET REASON='     WS-RC-DISP
                   SET NO-MORE-MSGS TO TRUE
                   ADD 1 TO WS-MQ-ERRORS
           END-EVALUATE.

       2200-VALIDATE-PAYLOAD.
           IF MQ-PAY-CIF-NUMBER = SPACES OR LOW-VALUES
               MOVE 'BAD CIF       ' TO WS-DET-STATUS
               SET MSG-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-PAYLOAD
               EXIT PARAGRAPH
           END-IF
           IF MQ-PAY-TRAN-TYPE NOT = 'DP' AND NOT = 'WD'
               MOVE 'BAD TRAN TYPE ' TO WS-DET-STATUS
               SET MSG-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-PAYLOAD
               EXIT PARAGRAPH
           END-IF
           IF MQ-PAY-AMOUNT <= ZERO
               MOVE 'AMOUNT LE ZERO' TO WS-DET-STATUS
               SET MSG-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-PAYLOAD
           END-IF.

       2300-DB2-INSERT.
      *    TRAN_TYPE: CR (CREDIT) FOR DEPOSITS, DR (DEBIT) FOR WITHDRAWALS
      *    TRAN_CODE: DEPM (DEPOSIT VIA MQ) OR WITM (WITHDRAWAL VIA MQ)
      *    CHANNEL:   MQCP IDENTIFIES THIS AS AN MQ CONSUMER POSTING
           ADD 1 TO WS-TRAN-SEED
           MOVE WS-TRAN-SEED     TO HV-TRAN-ID
           MOVE MQ-PAY-ACCT-NUMBER TO HV-ACCT-NUMBER
           MOVE MQ-PAY-AMOUNT    TO HV-AMOUNT
           MOVE MQ-PAY-DATE      TO HV-TRAN-DATE

           IF MQ-PAY-DEPOSIT
               MOVE 'CR'   TO HV-DR-CR
               MOVE 'DEPM' TO HV-TRAN-CODE
               MOVE 'MQ DEPOSIT POSTED'      TO HV-TRAN-DESC
           ELSE
               MOVE 'DR'   TO HV-DR-CR
               MOVE 'WITM' TO HV-TRAN-CODE
               MOVE 'MQ WITHDRAWAL POSTED'   TO HV-TRAN-DESC
           END-IF

           EXEC SQL
               INSERT INTO BANK.TRANSACTION_HIST
                      (TRAN_ID,         ACCT_NUMBER,    TRAN_TYPE,
                       TRAN_CODE,       AMOUNT,         EFFECTIVE_DATE,
                       POST_DATE,       DESCRIPTION,    CHANNEL,
                       TRAN_STATUS)
               VALUES (:HV-TRAN-ID,     :HV-ACCT-NUMBER, :HV-DR-CR,
                       :HV-TRAN-CODE,   :HV-AMOUNT,      :HV-TRAN-DATE,
                       :HV-TRAN-DATE,   :HV-TRAN-DESC,   'MQCP',
                       'P')
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   ADD 1 TO WS-ROWS-INSERTED
                   MOVE 'DB2 POSTED    ' TO WS-DET-STATUS
               WHEN OTHER
                   DISPLAY 'DEPTMQC: DB2 INSERT ERROR SQLCODE=' SQLCODE
                           ' ACCT=' HV-ACCT-NUMBER
                   MOVE 'DB2 ERROR     ' TO WS-DET-STATUS
                   SET MSG-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-DB2-ERRORS
                   PERFORM 2310-MQ-BACKOUT
           END-EVALUATE.

       2310-MQ-BACKOUT.
      *    DB2 INSERT FAILED - ROLL BACK THE MQ GET FOR THIS MESSAGE
      *    SO IT RETURNS TO THE QUEUE AND CAN BE REPROCESSED OR SENT
      *    TO A DEAD-LETTER QUEUE BY MQ AFTER MQMD-BACKOUTCOUNT RETRIES.
           EXEC SQL ROLLBACK END-EXEC
           CALL 'MQBACK' USING MQ-HCONN
                               MQ-COMP-CODE
                               MQ-REASON-CODE
           IF MQ-COMP-CODE NOT = MQCC-OK
               MOVE MQ-REASON-CODE TO WS-RC-DISP
               DISPLAY 'DEPTMQC: MQBACK FAILED REASON=' WS-RC-DISP
           END-IF.

       2400-WRITE-DETAIL.
           MOVE MQ-PAY-CIF-NUMBER  TO WS-DET-CIF
           MOVE MQ-PAY-ACCT-NUMBER TO WS-DET-ACCT
           MOVE MQ-PAY-TRAN-TYPE   TO WS-DET-TYPE
           IF MQ-PAY-AMOUNT > ZERO
               MOVE MQ-PAY-AMOUNT  TO WS-DET-AMOUNT
           ELSE
               MOVE ZERO           TO WS-DET-AMOUNT
           END-IF
           WRITE RPT-RECORD FROM WS-DETAIL.

       2500-PERIODIC-COMMIT.
      *    COMMIT DB2 AND MQ TOGETHER SO BOTH UNITS OF WORK STAY IN SYNC.
      *    A FAILURE IN EITHER COMMIT LEAVES BOTH UNCOMMITTED; THE JOB CAN
      *    BE RESTARTED AND THE UNCONSUMED MESSAGES REMAIN ON THE QUEUE.
           ADD 1 TO WS-COMMIT-COUNT
           IF WS-COMMIT-COUNT >= WS-COMMIT-FREQ
               EXEC SQL COMMIT END-EXEC
               IF SQLCODE NOT = 0
                   DISPLAY 'DEPTMQC: DB2 COMMIT ERROR SQLCODE=' SQLCODE
                   ADD 1 TO WS-DB2-ERRORS
               ELSE
                   CALL 'MQCMIT' USING MQ-HCONN
                                       MQ-COMP-CODE
                                       MQ-REASON-CODE
                   IF MQ-COMP-CODE NOT = MQCC-OK
                       MOVE MQ-REASON-CODE TO WS-RC-DISP
                       DISPLAY 'DEPTMQC: MQCMIT FAILED REASON='
                               WS-RC-DISP
                       ADD 1 TO WS-MQ-ERRORS
                   ELSE
                       DISPLAY 'DEPTMQC: COMMIT AT MESSAGE '
                               WS-MSGS-READ
                   END-IF
               END-IF
               MOVE ZERO TO WS-COMMIT-COUNT
           END-IF.

       2900-FINAL-COMMIT.
           IF WS-ROWS-INSERTED > ZERO
               EXEC SQL COMMIT END-EXEC
               IF SQLCODE NOT = 0
                   DISPLAY 'DEPTMQC: FINAL DB2 COMMIT ERROR SQLCODE='
                           SQLCODE
                   ADD 1 TO WS-DB2-ERRORS
               ELSE
                   CALL 'MQCMIT' USING MQ-HCONN
                                       MQ-COMP-CODE
                                       MQ-REASON-CODE
                   IF MQ-COMP-CODE NOT = MQCC-OK
                       MOVE MQ-REASON-CODE TO WS-RC-DISP
                       DISPLAY 'DEPTMQC: FINAL MQCMIT FAILED REASON='
                               WS-RC-DISP
                       ADD 1 TO WS-MQ-ERRORS
                   END-IF
               END-IF
           END-IF.

       3000-FINALIZE.
           PERFORM 3100-MQ-CLOSE
           PERFORM 3200-MQ-DISCONNECT
           CLOSE MQCRPT
           DISPLAY 'DEPTMQC: MQ DEPOSIT CONSUMER COMPLETE'
           DISPLAY 'MESSAGES READ:       ' WS-MSGS-READ
           DISPLAY 'ROWS INSERTED:       ' WS-ROWS-INSERTED
           DISPLAY 'INVALID PAYLOAD:     ' WS-INVALID-PAYLOAD
           DISPLAY 'MQ ERRORS:           ' WS-MQ-ERRORS
           DISPLAY 'DB2 ERRORS:          ' WS-DB2-ERRORS
           IF WS-MQ-ERRORS > ZERO OR WS-DB2-ERRORS > ZERO
               MOVE 8 TO RETURN-CODE
           ELSE IF WS-INVALID-PAYLOAD > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.

       3100-MQ-CLOSE.
           IF MQ-OPEN
               MOVE MQCO-NONE TO MQ-CLOSE-OPTIONS
               CALL 'MQCLOSE' USING MQ-HCONN
                                    MQ-HOBJ
                                    MQ-CLOSE-OPTIONS
                                    MQ-COMP-CODE
                                    MQ-REASON-CODE
               IF MQ-COMP-CODE NOT = MQCC-OK
                   MOVE MQ-REASON-CODE TO WS-RC-DISP
                   DISPLAY 'DEPTMQC: MQCLOSE REASON=' WS-RC-DISP
               END-IF
               SET MQ-NOT-OPEN TO TRUE
           END-IF.

       3200-MQ-DISCONNECT.
           IF MQ-CONNECTED
               CALL 'MQDISC' USING MQ-HCONN
                                   MQ-COMP-CODE
                                   MQ-REASON-CODE
               IF MQ-COMP-CODE NOT = MQCC-OK
                   MOVE MQ-REASON-CODE TO WS-RC-DISP
                   DISPLAY 'DEPTMQC: MQDISC REASON=' WS-RC-DISP
               ELSE
                   DISPLAY 'DEPTMQC: DISCONNECTED FROM QM '
                           MQ-QMGR-NAME
               END-IF
               SET MQ-NOT-CONNECTED TO TRUE
           END-IF.
