       IDENTIFICATION DIVISION.
       PROGRAM-ID. DORMACCT.
      *****************************************************************
      * DORMANT ACCOUNT PROCESSING PROGRAM                           *
      * DESCRIPTION: Identifies and processes dormant accounts per   *
      *   state escheatment laws. Accounts with no owner-initiated   *
      *   activity for the statutory period are flagged dormant and  *
      *   eventually escheated to the state.                         *
      * INPUT:  DB2 BANK.ACCOUNT   (dormant/escheatment candidates)  *
      *         PARMFILE (SYSIN)   - run parameters                  *
      * OUTPUT: DORMNOT  - Dormant notification letters              *
      *         ESCHRPT  - Escheatment report for state filing        *
      *         DB2 BANK.ACCOUNT   (status updated)                  *
      *         DB2 BANK.REGULATORY_RPT (escheatment records)        *
      * DB2 PLAN: ACCTPLAN                                           *
      * FREQUENCY: Monthly (first business day of month)            *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DORMNOT ASSIGN TO DORMNOT
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT ESCHRPT ASSIGN TO ESCHRPT
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT PARMFILE ASSIGN TO PARMCARD
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  DORMNOT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  DORM-NOTE-RECORD          PIC X(133).

       FD  ESCHRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  ESCH-RPT-RECORD           PIC X(133).

       FD  PARMFILE
           RECORDING MODE IS V.
       01  PARM-RECORD               PIC X(80).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

       COPY WSCOMMON.
       COPY ERRORCD.
       COPY ACCTMAST.
       COPY CUSTMAST.

      *-----------------------------------------------------------------
      * PARAMETER CARD STRUCTURE
      *-----------------------------------------------------------------
       01  WS-PARM-RECORD.
           05  WS-PARM-DORM-YEARS    PIC 9(02).
           05  FILLER                PIC X(01).
           05  WS-PARM-ESCH-YEARS   PIC 9(02).
           05  FILLER                PIC X(01).
           05  WS-PARM-STATE        PIC X(02).
           05  FILLER                PIC X(72).

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES
      *-----------------------------------------------------------------
       01  WS-DORM-HV.
           05  HV-ACCT-NUMBER        PIC X(12).
           05  HV-ACCT-TYPE          PIC X(03).
           05  HV-ACCT-STATUS        PIC X(01).
           05  HV-CIF-NUMBER         PIC X(10).
           05  HV-CURRENT-BALANCE    PIC S9(13)V99 COMP-3.
           05  HV-LAST-ACTIVITY-DATE PIC X(10).
           05  HV-FIRST-NAME         PIC X(25).
           05  HV-LAST-NAME          PIC X(30).
           05  HV-ADDR1              PIC X(40).
           05  HV-CITY               PIC X(25).
           05  HV-STATE              PIC X(02).
           05  HV-ZIP                PIC X(10).
           05  HV-DORM-CUTOFF-DATE   PIC X(10).
           05  HV-ESCH-CUTOFF-DATE   PIC X(10).
           05  HV-RPT-ID             PIC S9(9) COMP.

      *-----------------------------------------------------------------
      * DORMANT ACCOUNT CURSOR
      *-----------------------------------------------------------------
           EXEC SQL
               DECLARE DORM_CURSOR CURSOR FOR
               SELECT A.ACCT_NUMBER,
                      A.ACCT_TYPE,
                      A.ACCT_STATUS,
                      A.CIF_NUMBER,
                      A.CURRENT_BALANCE,
                      A.LAST_ACTIVITY_DATE,
                      C.FIRST_NAME,
                      C.LAST_NAME,
                      C.ADDR_LINE1,
                      C.CITY,
                      C.STATE,
                      C.ZIP
               FROM   BANK.ACCOUNT A
               INNER JOIN BANK.CUSTOMER C
                      ON A.CIF_NUMBER = C.CIF_NUMBER
               WHERE  A.ACCT_STATUS IN ('O','D')
               AND    A.LAST_ACTIVITY_DATE < :HV-DORM-CUTOFF-DATE
               AND    A.ACCT_TYPE IN ('CHK','SAV','MMA','CDA','IRA')
               AND    A.CURRENT_BALANCE > 0
               ORDER  BY A.LAST_ACTIVITY_DATE ASC
               FOR    UPDATE OF ACCT_STATUS,
                                LAST_UPDATE_TS,
                                LAST_UPDATE_USER
           END-EXEC.

      *-----------------------------------------------------------------
      * NOTIFICATION LETTER LINES
      *-----------------------------------------------------------------
       01  WS-NOTE-HEADER.
           05  FILLER PIC X(30)
               VALUE 'FIRST NATIONAL BANK'.
           05  FILLER PIC X(40)
               VALUE '       DORMANT ACCOUNT NOTIFICATION'.
           05  FILLER PIC X(63) VALUE SPACES.

       01  WS-NOTE-DETAIL.
           05  WS-ND-ACCT            PIC X(12).
           05  FILLER                PIC X(02) VALUE SPACES.
           05  WS-ND-NAME            PIC X(56).
           05  FILLER                PIC X(02) VALUE SPACES.
           05  WS-ND-BALANCE         PIC ZZZ,ZZZ,ZZZ,ZZ9.99.
           05  FILLER                PIC X(02) VALUE SPACES.
           05  WS-ND-LAST-ACTVTY     PIC X(10).
           05  FILLER                PIC X(02) VALUE SPACES.
           05  WS-ND-STATUS          PIC X(08).

      *-----------------------------------------------------------------
      * COUNTERS
      *-----------------------------------------------------------------
       01  WS-DORM-CNTS.
           05  WS-ACCTS-EVALUATED   PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-DORM-FLAGGED      PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-ESCH-CANDIDATES   PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-NOTES-GENERATED   PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-TOTAL-DORM-BAL    PIC S9(15)V99 COMP-3 VALUE ZERO.
           05  WS-TOTAL-ESCH-BAL    PIC S9(15)V99 COMP-3 VALUE ZERO.
           05  WS-DORM-ERRORS       PIC 9(05) COMP-3 VALUE ZERO.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS-DORMANT-ACCOUNTS
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'DORMACCT: DORMANT ACCOUNT PROCESSING STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE '-'
                  DELIMITED BY SIZE WS-CURRENT-MONTH
                  DELIMITED BY SIZE '-' DELIMITED BY SIZE
                  WS-CURRENT-DAY DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           OPEN INPUT  PARMFILE
           OPEN OUTPUT DORMNOT
           OPEN OUTPUT ESCHRPT

           READ PARMFILE INTO WS-PARM-RECORD
           DISPLAY 'DORMACCT: PARM - DORM YEARS=' WS-PARM-DORM-YEARS
                   ' ESCH YEARS=' WS-PARM-ESCH-YEARS
                   ' STATE=' WS-PARM-STATE

           WRITE DORM-NOTE-RECORD FROM WS-NOTE-HEADER

      *    CALCULATE DORMANCY AND ESCHEATMENT CUTOFF DATES
           EXEC SQL
               SELECT CHAR(DATE(:WS-BUSINESS-DATE) -
                           :WS-PARM-DORM-YEARS YEARS)
               INTO   :HV-DORM-CUTOFF-DATE
               FROM   SYSIBM.SYSDUMMY1
           END-EXEC

           EXEC SQL
               SELECT CHAR(DATE(:WS-BUSINESS-DATE) -
                           :WS-PARM-ESCH-YEARS YEARS)
               INTO   :HV-ESCH-CUTOFF-DATE
               FROM   SYSIBM.SYSDUMMY1
           END-EXEC

           DISPLAY 'DORMACCT: DORMANCY CUTOFF=' HV-DORM-CUTOFF-DATE
           DISPLAY 'DORMACCT: ESCHEATMENT CUTOFF=' HV-ESCH-CUTOFF-DATE

           EXEC SQL OPEN DORM_CURSOR END-EXEC
           IF SQLCODE NOT = 0
               DISPLAY 'DORMACCT: CANNOT OPEN DORM_CURSOR SQLCODE='
                       SQLCODE
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.

       2000-PROCESS-DORMANT-ACCOUNTS.
           PERFORM 2100-FETCH-ACCOUNT
               UNTIL SQLCODE = +100 OR FATAL-ERROR-FOUND.

       2100-FETCH-ACCOUNT.
           EXEC SQL
               FETCH DORM_CURSOR
               INTO  :HV-ACCT-NUMBER,
                     :HV-ACCT-TYPE,
                     :HV-ACCT-STATUS,
                     :HV-CIF-NUMBER,
                     :HV-CURRENT-BALANCE,
                     :HV-LAST-ACTIVITY-DATE,
                     :HV-FIRST-NAME,
                     :HV-LAST-NAME,
                     :HV-ADDR1,
                     :HV-CITY,
                     :HV-STATE,
                     :HV-ZIP
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   ADD 1 TO WS-ACCTS-EVALUATED
                   PERFORM 2200-DETERMINE-DORM-STATUS
               WHEN +100
                   CONTINUE
               WHEN OTHER
                   DISPLAY 'DORMACCT: FETCH ERROR SQLCODE=' SQLCODE
                   SET FATAL-ERROR-FOUND TO TRUE
           END-EVALUATE.

       2200-DETERMINE-DORM-STATUS.
           IF HV-LAST-ACTIVITY-DATE < HV-ESCH-CUTOFF-DATE
               PERFORM 2300-PROCESS-ESCHEATMENT
           ELSE IF HV-LAST-ACTIVITY-DATE < HV-DORM-CUTOFF-DATE
               PERFORM 2400-FLAG-AS-DORMANT
           END-IF.

       2300-PROCESS-ESCHEATMENT.
           ADD 1 TO WS-ESCH-CANDIDATES
           ADD HV-CURRENT-BALANCE TO WS-TOTAL-ESCH-BAL

           EXEC SQL
               UPDATE BANK.ACCOUNT
               SET    ACCT_STATUS      = 'E',
                      LAST_UPDATE_TS   = CURRENT TIMESTAMP,
                      LAST_UPDATE_USER = 'DORMACCT'
               WHERE  CURRENT OF DORM_CURSOR
           END-EXEC

           IF SQLCODE = 0
               EXEC SQL
                   INSERT INTO BANK.REGULATORY_RPT
                          (RPT_TYPE, CIF_NUMBER, ACCT_NUMBER,
                           TRAN_DATE, TRAN_AMOUNT, RPT_STATUS,
                           CREATED_BY)
                   VALUES ('BSA ', :HV-CIF-NUMBER, :HV-ACCT-NUMBER,
                           :WS-BUSINESS-DATE, :HV-CURRENT-BALANCE,
                           'P', 'DORMACCT')
               END-EXEC

               MOVE HV-ACCT-NUMBER TO WS-ND-ACCT
               STRING HV-FIRST-NAME DELIMITED BY SPACE ' '
                      DELIMITED BY SIZE HV-LAST-NAME DELIMITED BY SPACE
                      INTO WS-ND-NAME
               MOVE HV-CURRENT-BALANCE TO WS-ND-BALANCE
               MOVE HV-LAST-ACTIVITY-DATE TO WS-ND-LAST-ACTVTY
               MOVE 'ESCHEATED' TO WS-ND-STATUS
               WRITE ESCH-RPT-RECORD FROM WS-NOTE-DETAIL
           ELSE
               ADD 1 TO WS-DORM-ERRORS
           END-IF.

       2400-FLAG-AS-DORMANT.
           ADD 1 TO WS-DORM-FLAGGED
           ADD HV-CURRENT-BALANCE TO WS-TOTAL-DORM-BAL

           EXEC SQL
               UPDATE BANK.ACCOUNT
               SET    ACCT_STATUS      = 'D',
                      LAST_UPDATE_TS   = CURRENT TIMESTAMP,
                      LAST_UPDATE_USER = 'DORMACCT'
               WHERE  CURRENT OF DORM_CURSOR
           END-EXEC

           IF SQLCODE = 0
               ADD 1 TO WS-NOTES-GENERATED
               MOVE HV-ACCT-NUMBER TO WS-ND-ACCT
               STRING HV-FIRST-NAME DELIMITED BY SPACE ' '
                      DELIMITED BY SIZE HV-LAST-NAME DELIMITED BY SPACE
                      INTO WS-ND-NAME
               MOVE HV-CURRENT-BALANCE TO WS-ND-BALANCE
               MOVE HV-LAST-ACTIVITY-DATE TO WS-ND-LAST-ACTVTY
               MOVE 'DORMANT' TO WS-ND-STATUS
               WRITE DORM-NOTE-RECORD FROM WS-NOTE-DETAIL
               ADD 1 TO WS-COMMIT-COUNT
               IF WS-COMMIT-COUNT >= WS-COMMIT-FREQ
                   EXEC SQL COMMIT END-EXEC
                   MOVE ZERO TO WS-COMMIT-COUNT
               END-IF
           ELSE
               ADD 1 TO WS-DORM-ERRORS
           END-IF.

       3000-FINALIZE.
           EXEC SQL COMMIT END-EXEC
           EXEC SQL CLOSE DORM_CURSOR END-EXEC

           CLOSE PARMFILE DORMNOT ESCHRPT

           DISPLAY 'DORMACCT: DORMANT ACCOUNT PROCESSING COMPLETE'
           DISPLAY 'ACCOUNTS EVALUATED:  ' WS-ACCTS-EVALUATED
           DISPLAY 'DORMANT FLAGGED:     ' WS-DORM-FLAGGED
           DISPLAY 'ESCH CANDIDATES:     ' WS-ESCH-CANDIDATES
           DISPLAY 'NOTICES GENERATED:   ' WS-NOTES-GENERATED
           DISPLAY 'TOTAL DORMANT BAL:   ' WS-TOTAL-DORM-BAL
           DISPLAY 'TOTAL ESCH BAL:      ' WS-TOTAL-ESCH-BAL
           DISPLAY 'ERRORS:              ' WS-DORM-ERRORS

           IF WS-DORM-ERRORS > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
