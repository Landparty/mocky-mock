       IDENTIFICATION DIVISION.
       PROGRAM-ID. MQBATCH.
      *================================================================*
      * Program type: IBM MQ batch consumer/producer.                  *
      * MQCONN / MQOPEN / MQGET with wait / MQPUT1 reply / MQCMIT /    *
      * MQCLOSE / MQDISC against the MQ object descriptors that COPY   *
      * CMQV, CMQODV, CMQMDV and CMQGMOV normally bring in.            *
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  MQ-CONSTANTS.
           05  MQOO-INPUT-SHARED   PIC S9(9) BINARY VALUE 2.
           05  MQOO-OUTPUT         PIC S9(9) BINARY VALUE 16.
           05  MQGMO-WAIT          PIC S9(9) BINARY VALUE 1.
           05  MQGMO-SYNCPOINT     PIC S9(9) BINARY VALUE 2.
           05  MQGMO-CONVERT       PIC S9(9) BINARY VALUE 16384.
           05  MQCO-NONE           PIC S9(9) BINARY VALUE 0.
           05  MQCC-OK             PIC S9(9) BINARY VALUE 0.
           05  MQCC-FAILED         PIC S9(9) BINARY VALUE 2.
           05  MQRC-NO-MSG-AVAILABLE PIC S9(9) BINARY VALUE 2033.
           05  MQPER-PERSISTENT    PIC S9(9) BINARY VALUE 1.
       01  MQ-HANDLES.
           05  WS-HCONN            PIC S9(9) BINARY.
           05  WS-HOBJ             PIC S9(9) BINARY.
           05  WS-OPTIONS          PIC S9(9) BINARY.
           05  WS-COMPCODE         PIC S9(9) BINARY.
           05  WS-REASON           PIC S9(9) BINARY.
           05  WS-BUFFLEN          PIC S9(9) BINARY.
           05  WS-DATALEN          PIC S9(9) BINARY.
       01  WS-QMGR-NAME            PIC X(48) VALUE 'QM01'.
       01  MQOD.
           05  MQOD-STRUCID        PIC X(4) VALUE 'OD  '.
           05  MQOD-VERSION        PIC S9(9) BINARY VALUE 1.
           05  MQOD-OBJECTTYPE     PIC S9(9) BINARY VALUE 1.
           05  MQOD-OBJECTNAME     PIC X(48).
           05  MQOD-OBJECTQMGRNAME PIC X(48).
           05  MQOD-DYNAMICQNAME   PIC X(48).
           05  MQOD-ALTERNATEUSERID PIC X(12).
       01  MQMD.
           05  MQMD-STRUCID        PIC X(4) VALUE 'MD  '.
           05  MQMD-VERSION        PIC S9(9) BINARY VALUE 1.
           05  MQMD-REPORT         PIC S9(9) BINARY VALUE 0.
           05  MQMD-MSGTYPE        PIC S9(9) BINARY VALUE 8.
           05  MQMD-EXPIRY         PIC S9(9) BINARY VALUE -1.
           05  MQMD-FEEDBACK       PIC S9(9) BINARY VALUE 0.
           05  MQMD-ENCODING       PIC S9(9) BINARY VALUE 785.
           05  MQMD-CODEDCHARSETID PIC S9(9) BINARY VALUE 500.
           05  MQMD-FORMAT         PIC X(8) VALUE 'MQSTR   '.
           05  MQMD-PRIORITY       PIC S9(9) BINARY VALUE -1.
           05  MQMD-PERSISTENCE    PIC S9(9) BINARY VALUE 2.
           05  MQMD-MSGID          PIC X(24) VALUE LOW-VALUES.
           05  MQMD-CORRELID       PIC X(24) VALUE LOW-VALUES.
           05  MQMD-REPLYTOQ       PIC X(48).
           05  MQMD-REPLYTOQMGR    PIC X(48).
       01  MQGMO.
           05  MQGMO-STRUCID       PIC X(4) VALUE 'GMO '.
           05  MQGMO-VERSION       PIC S9(9) BINARY VALUE 1.
           05  MQGMO-OPTIONS       PIC S9(9) BINARY VALUE 0.
           05  MQGMO-WAITINTERVAL  PIC S9(9) BINARY VALUE 5000.
       01  MQPMO.
           05  MQPMO-STRUCID       PIC X(4) VALUE 'PMO '.
           05  MQPMO-VERSION       PIC S9(9) BINARY VALUE 1.
           05  MQPMO-OPTIONS       PIC S9(9) BINARY VALUE 2.
       01  WS-MESSAGE-BUFFER.
           05  MSG-TRAN-TYPE       PIC X(4).
           05  MSG-ACCT-NO         PIC X(10).
           05  MSG-AMOUNT          PIC 9(9)V99.
           05  FILLER              PIC X(75).
       01  WS-REPLY-BUFFER         PIC X(100).
       01  WS-MSG-COUNT            PIC 9(7) COMP VALUE 0.
       01  WS-DRAIN-DONE           PIC X VALUE 'N'.
           88  DRAIN-DONE          VALUE 'Y'.
       PROCEDURE DIVISION.
       0000-MAIN.
           CALL 'MQCONN' USING WS-QMGR-NAME WS-HCONN
                               WS-COMPCODE WS-REASON
           IF WS-COMPCODE NOT = MQCC-OK
               DISPLAY 'MQCONN FAILED RC=' WS-REASON
               MOVE 12 TO RETURN-CODE
               GOBACK
           END-IF
           MOVE 'BANK.DEPOSIT.QUEUE' TO MQOD-OBJECTNAME
           COMPUTE WS-OPTIONS = MQOO-INPUT-SHARED
           CALL 'MQOPEN' USING WS-HCONN MQOD WS-OPTIONS WS-HOBJ
                               WS-COMPCODE WS-REASON
           IF WS-COMPCODE NOT = MQCC-OK
               DISPLAY 'MQOPEN FAILED RC=' WS-REASON
               PERFORM 9000-DISCONNECT
               GOBACK
           END-IF
           PERFORM 1000-DRAIN-QUEUE UNTIL DRAIN-DONE
           CALL 'MQCLOSE' USING WS-HCONN WS-HOBJ MQCO-NONE
                                WS-COMPCODE WS-REASON
           PERFORM 9000-DISCONNECT
           DISPLAY 'MESSAGES PROCESSED: ' WS-MSG-COUNT
           GOBACK.
       1000-DRAIN-QUEUE.
           COMPUTE MQGMO-OPTIONS = MQGMO-WAIT + MQGMO-SYNCPOINT
                                 + MQGMO-CONVERT
           MOVE LENGTH OF WS-MESSAGE-BUFFER TO WS-BUFFLEN
           MOVE LOW-VALUES TO MQMD-MSGID MQMD-CORRELID
           CALL 'MQGET' USING WS-HCONN WS-HOBJ MQMD MQGMO
                              WS-BUFFLEN WS-MESSAGE-BUFFER WS-DATALEN
                              WS-COMPCODE WS-REASON
           EVALUATE TRUE
               WHEN WS-COMPCODE = MQCC-OK
                   ADD 1 TO WS-MSG-COUNT
                   PERFORM 1100-REPLY
                   CALL 'MQCMIT' USING WS-HCONN WS-COMPCODE WS-REASON
               WHEN WS-REASON = MQRC-NO-MSG-AVAILABLE
                   SET DRAIN-DONE TO TRUE
               WHEN OTHER
                   DISPLAY 'MQGET FAILED RC=' WS-REASON
                   CALL 'MQBACK' USING WS-HCONN WS-COMPCODE WS-REASON
                   SET DRAIN-DONE TO TRUE
           END-EVALUATE.
       1100-REPLY.
           MOVE MQMD-REPLYTOQ TO MQOD-OBJECTNAME
           MOVE MQMD-REPLYTOQMGR TO MQOD-OBJECTQMGRNAME
           STRING 'ACK ' MSG-ACCT-NO DELIMITED BY SIZE
               INTO WS-REPLY-BUFFER
           END-STRING
           MOVE MQMD-MSGID TO MQMD-CORRELID
           CALL 'MQPUT1' USING WS-HCONN MQOD MQMD MQPMO
                               WS-BUFFLEN WS-REPLY-BUFFER
                               WS-COMPCODE WS-REASON.
       9000-DISCONNECT.
           CALL 'MQDISC' USING WS-HCONN WS-COMPCODE WS-REASON.
