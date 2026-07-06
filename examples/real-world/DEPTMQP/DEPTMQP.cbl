       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEPTMQP.
      *****************************************************************
      * DEPOSIT MQ PRODUCER - IBM MQ BATCH MESSAGE PUBLISHER         *
      * DESCRIPTION: Reads deposit/withdrawal records from the       *
      *   DEPTIN sequential file, validates each record, builds     *
      *   a 74-byte MQ payload, and PUTs it to BANK.DEPOSIT.QUEUE  *
      *   on queue manager CSQ1. Messages participate in a unit     *
      *   of work; MQCMIT is issued every WS-CMIT-FREQ records.    *
      *   Downstream consumers receive persistent MQMT-DATAGRAM     *
      *   messages and process deposits asynchronously.             *
      * INPUT:  DEPTIN - sequential deposit records (50 bytes each) *
      *         FORMAT: CIF(10)+ACCT(12)+AMOUNT(15)+TYPE(2)+FIL(11)*
      * OUTPUT: BANK.DEPOSIT.QUEUE on QM CSQ1 (MQ messages)        *
      *         MQPRPT - processing report                          *
      * CALLS:  MQCONN, MQOPEN, MQPUT, MQCMIT, MQCLOSE, MQDISC    *
      * STEPLIB REQUIRES: MQ.V9R1M0.SCSQLOAD (MQ load library)    *
      * FREQUENCY: On-demand (submitted via DEPTMQJ.jcl)           *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DEPTIN  ASSIGN TO DEPTIN
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-DEPTIN-STATUS.
           SELECT MQPRPT  ASSIGN TO MQPRPT
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  DEPTIN
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  BATCH-DEPOSIT-REC.
           05  BATCH-CIF-NUMBER     PIC X(10).
           05  BATCH-ACCT-NUMBER    PIC X(12).
           05  BATCH-AMOUNT-CHAR    PIC X(15).
           05  BATCH-TRAN-TYPE      PIC X(02).
           05  BATCH-FILLER         PIC X(11).

       FD  MQPRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD               PIC X(133).

       WORKING-STORAGE SECTION.
           COPY WSCOMMON.
           COPY ERRORCD.
           COPY MQMSG.

       01  WS-DEPTIN-STATUS         PIC X(02).
           88  WS-DEPTIN-OK         VALUE '00'.
           88  WS-DEPTIN-EOF        VALUE '10'.

       01  WS-EDIT-WORK.
           05  WS-AMOUNT-WORK       PIC S9(11)V99.
           05  WS-AMOUNT-DISP       PIC ZZZ,ZZZ,ZZZ.99.

       01  WS-RECORD-ERROR          PIC X(01) VALUE 'N'.
           88  RECORD-ERROR-FOUND   VALUE 'Y'.
           88  RECORD-OK            VALUE 'N'.

       01  WS-MQ-FLAGS.
           05  WS-MQ-CONNECTED      PIC X(01) VALUE 'N'.
               88  MQ-CONNECTED     VALUE 'Y'.
               88  MQ-NOT-CONNECTED VALUE 'N'.
           05  WS-MQ-OPEN           PIC X(01) VALUE 'N'.
               88  MQ-OPEN          VALUE 'Y'.
               88  MQ-NOT-OPEN      VALUE 'N'.

       01  WS-CMIT-FREQ             PIC 9(05) COMP-3 VALUE 500.
       01  WS-CMIT-COUNT            PIC 9(05) COMP-3 VALUE ZERO.

       01  WS-COUNTERS.
           05  WS-RECS-READ         PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-MSGS-PUT          PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-INVALID-INPUT     PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-MQ-ERRORS         PIC 9(05) COMP-3 VALUE ZERO.

       01  WS-RC-DISP               PIC -(9)9.

       01  WS-HDR.
           05  FILLER PIC X(15) VALUE 'CIF            '.
           05  FILLER PIC X(15) VALUE 'ACCOUNT        '.
           05  FILLER PIC X(05) VALUE 'TYPE '.
           05  FILLER PIC X(20) VALUE '              AMOUNT'.
           05  FILLER PIC X(10) VALUE '  STATUS  '.

       01  WS-DETAIL.
           05  WS-DET-CIF           PIC X(10).
           05  FILLER               PIC X(05) VALUE SPACES.
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
           PERFORM 2000-PROCESS-DEPOSITS
               UNTIL WS-EOF
           PERFORM 2900-FINAL-COMMIT
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'DEPTMQP: MQ DEPOSIT PRODUCER STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR  DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-MONTH DELIMITED BY SIZE
                  '-'              DELIMITED BY SIZE
                  WS-CURRENT-DAY   DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING
           OPEN INPUT  DEPTIN
           OPEN OUTPUT MQPRPT
           WRITE RPT-RECORD FROM WS-HDR
           PERFORM 1100-MQ-CONNECT
           IF MQ-CONNECTED
               PERFORM 1200-MQ-OPEN
           END-IF
           READ DEPTIN
               AT END SET WS-EOF TO TRUE
           END-READ.

       1100-MQ-CONNECT.
      *    MQCONN ESTABLISHES A CONNECTION TO THE LOCAL QUEUE MANAGER.
      *    MQ-HCONN IS THE CONNECTION HANDLE USED IN ALL SUBSEQUENT CALLS.
           CALL 'MQCONN' USING MQ-QMGR-NAME
                               MQ-HCONN
                               MQ-COMP-CODE
                               MQ-REASON-CODE
           IF MQ-COMP-CODE = MQCC-OK
               SET MQ-CONNECTED TO TRUE
               DISPLAY 'DEPTMQP: CONNECTED TO QM ' MQ-QMGR-NAME
           ELSE
               MOVE MQ-COMP-CODE   TO WS-RC-DISP
               DISPLAY 'DEPTMQP: MQCONN FAILED CC=' WS-RC-DISP
               MOVE MQ-REASON-CODE TO WS-RC-DISP
               DISPLAY 'DEPTMQP: MQCONN REASON='    WS-RC-DISP
               ADD 1 TO WS-MQ-ERRORS
           END-IF.

       1200-MQ-OPEN.
      *    MQOPEN OPENS THE OUTPUT QUEUE. MQOO-OUTPUT (16) +
      *    MQOO-FAIL-IF-QUIESCE (32) = 48 PREVENTS PUTS DURING QM QUIESCE.
           MOVE MQ-QUEUE-NAME TO MQOD-OBJECTNAME
           COMPUTE MQ-OPEN-OPTIONS = MQOO-OUTPUT + MQOO-FAIL-IF-QUIESCE
           CALL 'MQOPEN' USING MQ-HCONN
                               MQOD
                               MQ-OPEN-OPTIONS
                               MQ-HOBJ
                               MQ-COMP-CODE
                               MQ-REASON-CODE
           IF MQ-COMP-CODE = MQCC-OK
               SET MQ-OPEN TO TRUE
               DISPLAY 'DEPTMQP: OPENED QUEUE ' MQ-QUEUE-NAME
           ELSE
               MOVE MQ-COMP-CODE   TO WS-RC-DISP
               DISPLAY 'DEPTMQP: MQOPEN FAILED CC=' WS-RC-DISP
               MOVE MQ-REASON-CODE TO WS-RC-DISP
               DISPLAY 'DEPTMQP: MQOPEN REASON='    WS-RC-DISP
               ADD 1 TO WS-MQ-ERRORS
           END-IF.

       2000-PROCESS-DEPOSITS.
           MOVE 'N' TO WS-RECORD-ERROR
           ADD 1 TO WS-RECS-READ
           PERFORM 2100-VALIDATE-RECORD
           IF RECORD-OK
               PERFORM 2200-BUILD-MQ-PAYLOAD
               PERFORM 2300-MQPUT
           END-IF
           PERFORM 2400-WRITE-DETAIL
           PERFORM 2500-PERIODIC-COMMIT
           READ DEPTIN
               AT END SET WS-EOF TO TRUE
           END-READ.

       2100-VALIDATE-RECORD.
           IF BATCH-CIF-NUMBER = SPACES OR LOW-VALUES
               MOVE 'CIF REQUIRED  ' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           IF BATCH-TRAN-TYPE NOT = 'DP' AND NOT = 'WD'
               MOVE 'BAD TRAN TYPE ' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           IF FUNCTION TEST-NUMVAL(BATCH-AMOUNT-CHAR) NOT = ZERO
               MOVE 'BAD AMOUNT    ' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
               EXIT PARAGRAPH
           END-IF
           COMPUTE WS-AMOUNT-WORK =
               FUNCTION NUMVAL(BATCH-AMOUNT-CHAR)
           IF WS-AMOUNT-WORK <= ZERO
               MOVE 'AMOUNT LE ZERO' TO WS-DET-STATUS
               SET RECORD-ERROR-FOUND TO TRUE
               ADD 1 TO WS-INVALID-INPUT
           END-IF.

       2200-BUILD-MQ-PAYLOAD.
      *    FILL DEPT-MQ-PAYLOAD WITH THE DEPOSIT DETAILS.
      *    MQ-PAY-SOURCE-SYS IDENTIFIES THE ORIGINATING BATCH JOB
      *    SO DOWNSTREAM CONSUMERS CAN AUDIT THE MESSAGE SOURCE.
           MOVE SPACES                TO DEPT-MQ-PAYLOAD
           MOVE BATCH-CIF-NUMBER      TO MQ-PAY-CIF-NUMBER
           MOVE BATCH-ACCT-NUMBER     TO MQ-PAY-ACCT-NUMBER
           MOVE WS-AMOUNT-WORK        TO MQ-PAY-AMOUNT
           MOVE BATCH-TRAN-TYPE       TO MQ-PAY-TRAN-TYPE
           MOVE WS-BUSINESS-DATE      TO MQ-PAY-DATE
           MOVE 'DEPTMQP '            TO MQ-PAY-SOURCE-SYS.

       2300-MQPUT.
      *    MQPMO-OPTIONS = MQPMO-SYNCPOINT (4) + MQPMO-NEW-MSG-ID (64)
      *    = 68. SYNCPOINT MEANS THE PUT JOINS THE CURRENT UOW AND IS
      *    COMMITTED OR BACKED OUT TOGETHER BY MQCMIT/MQBACK.
      *    MQPMO-NEW-MSG-ID INSTRUCTS MQ TO GENERATE A UNIQUE MSG ID.
           MOVE 'DEPTMQP             ' TO MQMD-PUTAPPLNAME
           MOVE MQ-PAYLOAD-LEN         TO MQ-MSG-LEN
           CALL 'MQPUT' USING MQ-HCONN
                              MQ-HOBJ
                              MQMD
                              MQPMO
                              MQ-MSG-LEN
                              DEPT-MQ-PAYLOAD
                              MQ-COMP-CODE
                              MQ-REASON-CODE
           EVALUATE MQ-COMP-CODE
               WHEN MQCC-OK
                   ADD 1 TO WS-MSGS-PUT
                   MOVE 'PUT OK        ' TO WS-DET-STATUS
               WHEN MQCC-WARNING
                   ADD 1 TO WS-MSGS-PUT
                   MOVE MQ-REASON-CODE TO WS-RC-DISP
                   DISPLAY 'DEPTMQP: MQPUT WARNING RC=' WS-RC-DISP
                           ' CIF=' BATCH-CIF-NUMBER
                   MOVE 'PUT WARNING   ' TO WS-DET-STATUS
               WHEN OTHER
                   MOVE MQ-COMP-CODE   TO WS-RC-DISP
                   DISPLAY 'DEPTMQP: MQPUT FAILED CC='  WS-RC-DISP
                   MOVE MQ-REASON-CODE TO WS-RC-DISP
                   DISPLAY 'DEPTMQP: MQPUT REASON='     WS-RC-DISP
                           ' CIF=' BATCH-CIF-NUMBER
                   MOVE 'PUT FAILED    ' TO WS-DET-STATUS
                   SET RECORD-ERROR-FOUND TO TRUE
                   ADD 1 TO WS-MQ-ERRORS
           END-EVALUATE.

       2400-WRITE-DETAIL.
           MOVE BATCH-CIF-NUMBER  TO WS-DET-CIF
           MOVE BATCH-ACCT-NUMBER TO WS-DET-ACCT
           MOVE BATCH-TRAN-TYPE   TO WS-DET-TYPE
           IF WS-AMOUNT-WORK > ZERO
               MOVE WS-AMOUNT-WORK TO WS-DET-AMOUNT
           ELSE
               MOVE ZERO TO WS-DET-AMOUNT
           END-IF
           WRITE RPT-RECORD FROM WS-DETAIL.

       2500-PERIODIC-COMMIT.
      *    MQCMIT COMMITS ALL SYNCPOINT PUTS SINCE THE LAST COMMIT.
      *    ON FAILURE, MQBACK WOULD ROLL BACK THE CURRENT UOW.
      *    THE COMMIT FREQUENCY MATCHES THE INPUT FILE CHECKPOINT
      *    INTERVAL IN DEPTBMP SO BOTH JOBS CAN PAIR UP IN A RESTART.
           ADD 1 TO WS-CMIT-COUNT
           IF WS-CMIT-COUNT >= WS-CMIT-FREQ
               CALL 'MQCMIT' USING MQ-HCONN
                                   MQ-COMP-CODE
                                   MQ-REASON-CODE
               IF MQ-COMP-CODE NOT = MQCC-OK
                   MOVE MQ-REASON-CODE TO WS-RC-DISP
                   DISPLAY 'DEPTMQP: MQCMIT FAILED REASON=' WS-RC-DISP
                   ADD 1 TO WS-MQ-ERRORS
               ELSE
                   DISPLAY 'DEPTMQP: COMMIT AT RECORD ' WS-RECS-READ
               END-IF
               MOVE ZERO TO WS-CMIT-COUNT
           END-IF.

       2900-FINAL-COMMIT.
           IF WS-MSGS-PUT > ZERO
               CALL 'MQCMIT' USING MQ-HCONN
                                   MQ-COMP-CODE
                                   MQ-REASON-CODE
               IF MQ-COMP-CODE NOT = MQCC-OK
                   MOVE MQ-REASON-CODE TO WS-RC-DISP
                   DISPLAY 'DEPTMQP: FINAL MQCMIT FAILED REASON='
                           WS-RC-DISP
                   ADD 1 TO WS-MQ-ERRORS
               END-IF
           END-IF.

       3000-FINALIZE.
           PERFORM 3100-MQ-CLOSE
           PERFORM 3200-MQ-DISCONNECT
           CLOSE DEPTIN
           CLOSE MQPRPT
           DISPLAY 'DEPTMQP: MQ DEPOSIT PRODUCER COMPLETE'
           DISPLAY 'RECORDS READ:        ' WS-RECS-READ
           DISPLAY 'MESSAGES PUT:        ' WS-MSGS-PUT
           DISPLAY 'INVALID INPUT:       ' WS-INVALID-INPUT
           DISPLAY 'MQ ERRORS:           ' WS-MQ-ERRORS
           IF WS-MQ-ERRORS > ZERO OR WS-INVALID-INPUT > ZERO
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
                   DISPLAY 'DEPTMQP: MQCLOSE REASON=' WS-RC-DISP
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
                   DISPLAY 'DEPTMQP: MQDISC REASON=' WS-RC-DISP
               ELSE
                   DISPLAY 'DEPTMQP: DISCONNECTED FROM QM '
                           MQ-QMGR-NAME
               END-IF
               SET MQ-NOT-CONNECTED TO TRUE
           END-IF.
