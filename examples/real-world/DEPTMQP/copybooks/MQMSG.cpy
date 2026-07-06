      *****************************************************************
      * IBM MQ STRUCTURES AND DEPOSIT MESSAGE PAYLOAD               *
      * COPYBOOK: MQMSG                                             *
      * DESCRIPTION: MQOD, MQMD, MQPMO structures, MQ constants,   *
      *   MQ handles/return codes, and deposit message payload.    *
      * REPLACES: CMQV (constants) and CMQP (parameter blocks)     *
      *   which are provided by the MQ installation at runtime.    *
      *   Reference: IBM MQ for z/OS V9 Application Programming.  *
      * USED BY: DEPTMQP, DEPTMQC                                           *
      *****************************************************************
      *
      * MQ CONSTANTS (SUBSET OF CMQV)
      *
       01  MQ-CONSTANTS.
      *    OBJECT TYPE
           05  MQOT-Q               PIC S9(09) COMP VALUE +1.
      *    OPEN OPTIONS (BITMASK - OR TOGETHER FOR MQOPEN)
           05  MQOO-OUTPUT          PIC S9(09) COMP VALUE +16.
           05  MQOO-FAIL-IF-QUIESCE PIC S9(09) COMP VALUE +32.
      *    PUT MESSAGE OPTIONS (BITMASK - OR TOGETHER FOR MQPMO-OPTIONS)
           05  MQPMO-SYNCPOINT      PIC S9(09) COMP VALUE +4.
           05  MQPMO-NEW-MSG-ID     PIC S9(09) COMP VALUE +64.
      *    MESSAGE TYPES
           05  MQMT-DATAGRAM        PIC S9(09) COMP VALUE +8.
      *    PERSISTENCE
           05  MQPER-PERSISTENT     PIC S9(09) COMP VALUE +1.
      *    PUT APPLICATION TYPE
           05  MQAT-BATCH           PIC S9(09) COMP VALUE +11.
      *    ENCODING (NATIVE IBM Z/OS)
           05  MQENC-NATIVE         PIC S9(09) COMP VALUE +785.
      *    CODED CHARACTER SET ID (EBCDIC)
           05  MQCCSI-EBCDIC        PIC S9(09) COMP VALUE +37.
      *    COMPLETION CODES
           05  MQCC-OK              PIC S9(09) COMP VALUE +0.
           05  MQCC-WARNING         PIC S9(09) COMP VALUE +1.
           05  MQCC-FAILED          PIC S9(09) COMP VALUE +2.
      *    REASON CODES (PARTIAL LIST)
           05  MQRC-NONE            PIC S9(09) COMP VALUE +0.
           05  MQRC-Q-FULL          PIC S9(09) COMP VALUE +2053.
           05  MQRC-NOT-OPEN        PIC S9(09) COMP VALUE +2019.
      *    OPEN OPTIONS FOR INPUT (BITMASK - USED BY MQGET PROGRAMS)
           05  MQOO-INPUT-SHARED    PIC S9(09) COMP VALUE +8.
           05  MQOO-INPUT-EXCLUSIVE PIC S9(09) COMP VALUE +4.
      *    GET MESSAGE OPTIONS (BITMASK - OR TOGETHER FOR MQGMO-OPTIONS)
           05  MQGMO-WAIT           PIC S9(09) COMP VALUE +1.
           05  MQGMO-NO-WAIT        PIC S9(09) COMP VALUE +0.
           05  MQGMO-SYNCPOINT      PIC S9(09) COMP VALUE +4.
           05  MQGMO-ACCEPT-TRUNC   PIC S9(09) COMP VALUE +64.
      *    WAIT INTERVAL
           05  MQWI-UNLIMITED       PIC S9(09) COMP VALUE -1.
      *    REASON CODES (GET-SPECIFIC)
           05  MQRC-NO-MSG-AVAIL    PIC S9(09) COMP VALUE +2033.
           05  MQRC-TRUNCATED-MSG   PIC S9(09) COMP VALUE +2080.
      *    CLOSE OPTIONS
           05  MQCO-NONE            PIC S9(09) COMP VALUE +0.
      *
      * OBJECT DESCRIPTOR (MQOD VERSION 1 = 168 BYTES)
      * IDENTIFIES THE QUEUE TO OPEN
      *
       01  MQOD.
           05  MQOD-STRUCID         PIC X(04) VALUE 'OD  '.
           05  MQOD-VERSION         PIC S9(09) COMP VALUE +1.
           05  MQOD-OBJECTTYPE      PIC S9(09) COMP VALUE +1.
           05  MQOD-OBJECTNAME      PIC X(48) VALUE SPACES.
           05  MQOD-OBJECTQMGRNAME  PIC X(48) VALUE SPACES.
           05  MQOD-DYNQNAME        PIC X(48) VALUE SPACES.
           05  MQOD-ALTUSERID       PIC X(12) VALUE SPACES.
      *
      * MESSAGE DESCRIPTOR (MQMD VERSION 1 = 324 BYTES)
      * POPULATED BY MQPUT; MQPMO-NEW-MSG-ID GENERATES MSGID AUTOMATICALLY
      *
       01  MQMD.
           05  MQMD-STRUCID         PIC X(04) VALUE 'MD  '.
           05  MQMD-VERSION         PIC S9(09) COMP VALUE +1.
           05  MQMD-REPORT          PIC S9(09) COMP VALUE +0.
           05  MQMD-MSGTYPE         PIC S9(09) COMP VALUE +8.
           05  MQMD-EXPIRY          PIC S9(09) COMP VALUE -1.
           05  MQMD-FEEDBACK        PIC S9(09) COMP VALUE +0.
           05  MQMD-ENCODING        PIC S9(09) COMP VALUE +785.
           05  MQMD-CODEDCHARSETID  PIC S9(09) COMP VALUE +37.
           05  MQMD-FORMAT          PIC X(08) VALUE 'MQSTR   '.
           05  MQMD-PRIORITY        PIC S9(09) COMP VALUE +0.
           05  MQMD-PERSISTENCE     PIC S9(09) COMP VALUE +1.
           05  MQMD-MSGID           PIC X(24) VALUE LOW-VALUES.
           05  MQMD-CORRELID        PIC X(24) VALUE LOW-VALUES.
           05  MQMD-BACKOUTCOUNT    PIC S9(09) COMP VALUE +0.
           05  MQMD-REPLYTOQ        PIC X(48) VALUE SPACES.
           05  MQMD-REPLYTOQMGR     PIC X(48) VALUE SPACES.
           05  MQMD-USERIDENTIFIER  PIC X(12) VALUE SPACES.
           05  MQMD-ACCOUNTINGTOKEN PIC X(32) VALUE LOW-VALUES.
           05  MQMD-APPLIDENTDATA   PIC X(32) VALUE SPACES.
           05  MQMD-PUTAPPLTYPE     PIC S9(09) COMP VALUE +11.
           05  MQMD-PUTAPPLNAME     PIC X(28) VALUE SPACES.
           05  MQMD-PUTDATE         PIC X(08) VALUE SPACES.
           05  MQMD-PUTTIME         PIC X(08) VALUE SPACES.
           05  MQMD-APPLORIGINDATA  PIC X(04) VALUE SPACES.
      *
      * GET MESSAGE OPTIONS (MQGMO VERSION 1 = 72 BYTES)
      * MQGMO-OPTIONS = MQGMO-SYNCPOINT (4) + MQGMO-NO-WAIT (0) = 4
      * SET MQGMO-WAIT (1) INSTEAD OF MQGMO-NO-WAIT FOR ONLINE CONSUMERS
      *
       01  MQGMO.
           05  MQGMO-STRUCID        PIC X(04) VALUE 'GMO '.
           05  MQGMO-VERSION        PIC S9(09) COMP VALUE +1.
           05  MQGMO-OPTIONS        PIC S9(09) COMP VALUE +4.
           05  MQGMO-WAITINTERVAL   PIC S9(09) COMP VALUE -1.
           05  MQGMO-SIGNAL1        PIC S9(09) COMP VALUE +0.
           05  MQGMO-SIGNAL2        PIC S9(09) COMP VALUE +0.
           05  MQGMO-RESOLVEDQNAME  PIC X(48) VALUE SPACES.
      *
      * PUT MESSAGE OPTIONS (MQPMO VERSION 1 = 128 BYTES)
      *
       01  MQPMO.
           05  MQPMO-STRUCID        PIC X(04) VALUE 'PMO '.
           05  MQPMO-VERSION        PIC S9(09) COMP VALUE +1.
           05  MQPMO-OPTIONS        PIC S9(09) COMP VALUE +68.
           05  MQPMO-TIMEOUT        PIC S9(09) COMP VALUE -1.
           05  MQPMO-CONTEXT        PIC S9(09) COMP VALUE +0.
           05  MQPMO-KNOWNDESTCOUNT PIC S9(09) COMP VALUE +0.
           05  MQPMO-UNKNWNDSTCOUNT PIC S9(09) COMP VALUE +0.
           05  MQPMO-INVLDDSTCOUNT  PIC S9(09) COMP VALUE +0.
           05  MQPMO-RESOLVEDQNAME  PIC X(48) VALUE SPACES.
           05  MQPMO-RESOLVEDQMGRN  PIC X(48) VALUE SPACES.
      *
      * MQ CONNECTION HANDLES AND RETURN CODES
      *
       01  MQ-HANDLES.
           05  MQ-HCONN             PIC S9(09) COMP VALUE +0.
           05  MQ-HOBJ              PIC S9(09) COMP VALUE +0.
           05  MQ-COMP-CODE         PIC S9(09) COMP VALUE +0.
           05  MQ-REASON-CODE       PIC S9(09) COMP VALUE +0.
           05  MQ-OPEN-OPTIONS      PIC S9(09) COMP VALUE +0.
           05  MQ-CLOSE-OPTIONS     PIC S9(09) COMP VALUE +0.
           05  MQ-MSG-LEN           PIC S9(09) COMP VALUE +0.
      *
      * DEPOSIT MQ MESSAGE PAYLOAD (WHAT IS PUT INTO THE QUEUE)
      * TOTAL: 74 BYTES
      *
       01  DEPT-MQ-PAYLOAD.
           05  MQ-PAY-CIF-NUMBER    PIC X(10).
           05  MQ-PAY-ACCT-NUMBER   PIC X(12).
           05  MQ-PAY-AMOUNT        PIC S9(11)V99 COMP-3.
           05  MQ-PAY-TRAN-TYPE     PIC X(02).
               88  MQ-PAY-DEPOSIT   VALUE 'DP'.
               88  MQ-PAY-WITHDRAW  VALUE 'WD'.
           05  MQ-PAY-DATE          PIC X(10).
           05  MQ-PAY-SOURCE-SYS    PIC X(08).
           05  MQ-PAY-FILLER        PIC X(25).
      *
       01  MQ-PAYLOAD-LEN           PIC S9(09) COMP VALUE +74.
       01  MQ-BUFFER-LEN            PIC S9(09) COMP VALUE +74.
       01  MQ-DATA-LEN              PIC S9(09) COMP VALUE +0.
      *
      * MQ QUEUE AND QUEUE MANAGER CONFIGURATION
      *
       01  MQ-CONFIG.
           05  MQ-QMGR-NAME         PIC X(48) VALUE 'CSQ1'.
           05  MQ-QUEUE-NAME        PIC X(48)
                                     VALUE 'BANK.DEPOSIT.QUEUE'.
