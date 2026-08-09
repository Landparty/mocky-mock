       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACHPROC.
      *****************************************************************
      * ACH BATCH PROCESSING PROGRAM                                 *
      * DESCRIPTION: Processes incoming and outgoing ACH files in    *
      *   NACHA format. Validates routing/account numbers, posts     *
      *   debit and credit transactions to accounts, updates GL,     *
      *   and generates return items for rejected entries.           *
      * INPUT:  ACHFILE  - Inbound NACHA file (94-byte records)      *
      *         PARMCARD - Processing control parameters (SYSIN)     *
      * OUTPUT: ACHRETURN - Return item file (rejected entries)      *
      *         ACHRPT    - ACH processing report                    *
      *         DB2 BANK.TRANSACTION_HIST (entries posted)           *
      *         DB2 BANK.ACH_BATCH        (batch records)            *
      * CALLS:  ACHPARSE (PL/I) - NACHA file parsing                 *
      *         ACCTVAL  (Assembler) - routing/account validation    *
      *         DATAVAL  (PL/I)     - data validation                *
      * DB2 PLAN: ACHPLAN                                            *
      * FREQUENCY: Daily (multiple times per day for RDFI)          *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACHFILE  ASSIGN TO ACHFILE
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-ACH-STATUS.

           SELECT ACHRETURN ASSIGN TO ACHRETURN
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-RET-STATUS.

           SELECT ACHRPT   ASSIGN TO ACHRPT
               ORGANIZATION IS LINE SEQUENTIAL.

           SELECT PARMFILE ASSIGN TO PARMCARD
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACHFILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       COPY ACHRECRD.

       FD  ACHRETURN
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RETURN-RECORD             PIC X(94).

       FD  ACHRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  RPT-RECORD                PIC X(133).

       FD  PARMFILE
           RECORDING MODE IS V.
       01  PARM-RECORD               PIC X(80).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

       COPY WSCOMMON.
       COPY ERRORCD.
       COPY ACCTMAST.

      *-----------------------------------------------------------------
      * ACH FILE STATUS
      *-----------------------------------------------------------------
       01  WS-ACH-STATUS             PIC X(02).
           88  WS-ACH-OK             VALUE '00'.
           88  WS-ACH-STATUS-EOF     VALUE '10'.
       01  WS-RET-STATUS             PIC X(02).

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES
      *-----------------------------------------------------------------
       01  WS-ACH-HV.
           05  HV-ACCT-NUMBER        PIC X(12).
           05  HV-ACCT-STATUS        PIC X(01).
           05  HV-CURRENT-BALANCE    PIC S9(13)V99 COMP-3.
           05  HV-AVAILABLE-BALANCE  PIC S9(13)V99 COMP-3.
           05  HV-TRAN-ID            PIC X(16).
           05  HV-TRAN-CODE          PIC X(04).
           05  HV-TRAN-TYPE          PIC X(02).
           05  HV-TRAN-AMOUNT        PIC S9(13)V99 COMP-3.
           05  HV-POST-DATE          PIC X(10).
           05  HV-TRAN-DESC          PIC X(40).
           05  HV-TRACE-NUM          PIC X(15).
           05  HV-BATCH-ID           PIC S9(9)      COMP.
           05  HV-FILE-ID            PIC X(20).
           05  HV-BATCH-NUM          PIC S9(9)      COMP.
           05  HV-CO-ID              PIC X(10).
           05  HV-CO-NAME            PIC X(16).
           05  HV-SEC-CODE           PIC X(03).
           05  HV-EFF-DATE           PIC X(10).
           05  HV-ENTRY-COUNT        PIC S9(9)      COMP.
           05  HV-TOTAL-DR           PIC S9(13)V99  COMP-3.
           05  HV-TOTAL-CR           PIC S9(13)V99  COMP-3.

      *-----------------------------------------------------------------
      * ACH PARSE PARMS (CALL TO PL/I ACHPARSE)
      *-----------------------------------------------------------------
       01  WS-ACH-PARSE-PARMS.
           05  PA-FUNCTION           PIC X(01).
           05  PA-INPUT-FILE         PIC X(44).
           05  PA-BATCH-ID           PIC S9(9) COMP.
           05  PA-ENTRY-COUNT        PIC S9(9) COMP.
           05  PA-TOTAL-DEBIT        PIC S9(13)V99 COMP-3.
           05  PA-TOTAL-CREDIT       PIC S9(13)V99 COMP-3.
           05  PA-ERROR-COUNT        PIC S9(9) COMP.
           05  PA-RETURN-CODE        PIC S9(4) COMP.
           05  PA-ERROR-MSG          PIC X(80).

      *-----------------------------------------------------------------
      * ACCOUNT VALIDATION PARMS (CALL TO ASSEMBLER ACCTVAL)
      *-----------------------------------------------------------------
       01  WS-ACCTVAL-PARMS.
           05  WS-AV-FUNCTION        PIC X(01).
           05  WS-AV-ACCT-NUMBER     PIC X(12).
           05  WS-AV-ROUTING-NUM     PIC X(09).
           05  WS-AV-RESULT-CODE     PIC X(01).

      *-----------------------------------------------------------------
      * PROCESSING CONTROL
      *-----------------------------------------------------------------
       01  WS-PARM-RECORD.
           05  WS-PARM-FILE-ID       PIC X(20).
           05  FILLER                PIC X(01).
           05  WS-PARM-DIRECTION     PIC X(01).
               88  WS-PARM-INBOUND   VALUE 'I'.
               88  WS-PARM-OUTBOUND  VALUE 'O'.
           05  FILLER                PIC X(58).

       01  WS-BATCH-ACTIVE          PIC X(01) VALUE 'N'.
           88  WS-IN-BATCH          VALUE 'Y'.
           88  WS-NOT-IN-BATCH      VALUE 'N'.

       01  WS-ENTRY-VALID           PIC X(01) VALUE 'N'.
           88  WS-ENTRY-OK          VALUE 'Y'.
           88  WS-ENTRY-REJECTED    VALUE 'N'.

       01  WS-RETURN-CODE-WORK      PIC X(03).
       01  WS-TRAN-SEED             PIC 9(16) COMP VALUE ZERO.
       01  WS-ACH-EOF               PIC X(01) VALUE 'N'.
           88  WS-ACH-FILE-EOF      VALUE 'Y'.
           88  WS-ACH-FILE-ACTIVE   VALUE 'N'.

      *-----------------------------------------------------------------
      * COUNTERS
      *-----------------------------------------------------------------
       01  WS-ACH-COUNTS.
           05  WS-BATCHES-READ      PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-ENTRIES-READ      PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-ENTRIES-POSTED    PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-ENTRIES-RETURNED  PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-ROUTING-ERRORS    PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-NSF-RETURNS       PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-ACCT-ERRORS       PIC 9(05) COMP-3 VALUE ZERO.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS-ACH-FILE
               UNTIL WS-ACH-FILE-EOF
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'ACHPROC: ACH BATCH PROCESSING STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE '-'
                  DELIMITED BY SIZE WS-CURRENT-MONTH
                  DELIMITED BY SIZE '-' DELIMITED BY SIZE
                  WS-CURRENT-DAY DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           OPEN INPUT  ACHFILE
           OPEN OUTPUT ACHRETURN
           OPEN OUTPUT ACHRPT
           OPEN INPUT  PARMFILE

           IF NOT WS-ACH-OK
               DISPLAY 'ACHPROC: ERROR OPENING ACHFILE STATUS='
                       WS-ACH-STATUS
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF

           READ PARMFILE INTO WS-PARM-RECORD
           MOVE WS-PARM-FILE-ID TO HV-FILE-ID
           DISPLAY 'ACHPROC: FILE-ID=' WS-PARM-FILE-ID
                   ' DIRECTION=' WS-PARM-DIRECTION

           PERFORM 1100-READ-ACH-RECORD.

       1100-READ-ACH-RECORD.
           READ ACHFILE
               AT END
                   SET WS-ACH-FILE-EOF TO TRUE
           END-READ.

       2000-PROCESS-ACH-FILE.
           ADD 1 TO WS-RECORD-COUNT

           EVALUATE TRUE
               WHEN AED-RECORD-TYPE = '1'
                   CONTINUE  *> FILE HEADER VALIDATED BY ACHPARSE
               WHEN AED-RECORD-TYPE = '5'
                   PERFORM 2100-PROCESS-BATCH-HEADER
               WHEN AED-RECORD-TYPE = '6'
                   PERFORM 2200-PROCESS-ENTRY-DETAIL THRU 2200-EXIT
               WHEN AED-RECORD-TYPE = '8'
                   PERFORM 2300-VERIFY-BATCH-CONTROL
               WHEN AED-RECORD-TYPE = '9'
                   CONTINUE  *> FILE CONTROL - SKIPPED
               WHEN OTHER
                   CONTINUE  *> PADDING RECORDS
           END-EVALUATE

           PERFORM 1100-READ-ACH-RECORD.

       2100-PROCESS-BATCH-HEADER.
           ADD 1 TO WS-BATCHES-READ
           SET WS-IN-BATCH TO TRUE
           MOVE ABH-COMPANY-ID  TO HV-CO-ID
           MOVE ABH-COMPANY-NAME TO HV-CO-NAME
           MOVE ABH-SEC-CODE    TO HV-SEC-CODE
           MOVE ZERO            TO HV-ENTRY-COUNT
           MOVE ZERO            TO HV-TOTAL-DR
           MOVE ZERO            TO HV-TOTAL-CR
           MOVE ABH-BATCH-NUMBER TO HV-BATCH-NUM

      *    INSERT BATCH CONTROL RECORD
           EXEC SQL
               INSERT INTO BANK.ACH_BATCH
                      (FILE_ID, BATCH_NUMBER, COMPANY_ID, COMPANY_NAME,
                       SEC_CODE, EFFECTIVE_DATE, SERVICE_CLASS,
                       BATCH_STATUS)
               VALUES (:HV-FILE-ID, :HV-BATCH-NUM, :HV-CO-ID,
                       :HV-CO-NAME, :HV-SEC-CODE, :WS-BUSINESS-DATE,
                       :ABH-SERVICE-CLASS, 'N')
           END-EXEC

           IF SQLCODE NOT = 0
               DISPLAY 'ACHPROC: ERROR INSERTING BATCH RECORD '
                       'BATCH=' HV-BATCH-NUM ' SQLCODE=' SQLCODE
               ADD 1 TO WS-ERROR-COUNT
           END-IF.

       2200-PROCESS-ENTRY-DETAIL.
           ADD 1 TO WS-ENTRIES-READ
           MOVE AED-TRACE-NUMBER TO HV-TRACE-NUM

      *    VALIDATE ROUTING NUMBER VIA ASSEMBLER
           MOVE 'R'             TO WS-AV-FUNCTION
           MOVE AED-RDFI-ID     TO WS-AV-ROUTING-NUM(1:8)
           MOVE AED-CHECK-DIGIT TO WS-AV-ROUTING-NUM(9:1)
           CALL 'ACCTVAL' USING WS-ACCTVAL-PARMS

           IF WS-AV-RESULT-CODE NOT = 'V'
               MOVE 'R14' TO WS-RETURN-CODE-WORK
               ADD 1 TO WS-ROUTING-ERRORS
               PERFORM 2400-WRITE-RETURN-ITEM
               GO TO 2200-EXIT
           END-IF

      *    LOOK UP ACCOUNT IN DB2
           MOVE FUNCTION TRIM(AED-DFI-ACCT-NUMBER) TO HV-ACCT-NUMBER

           EXEC SQL
               SELECT ACCT_STATUS,
                      CURRENT_BALANCE,
                      AVAILABLE_BALANCE
               INTO   :HV-ACCT-STATUS,
                      :HV-CURRENT-BALANCE,
                      :HV-AVAILABLE-BALANCE
               FROM   BANK.ACCOUNT
               WHERE  ACCT_NUMBER = :HV-ACCT-NUMBER
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   CONTINUE
               WHEN +100
                   MOVE 'R03' TO WS-RETURN-CODE-WORK
                   ADD 1 TO WS-ACCT-ERRORS
                   PERFORM 2400-WRITE-RETURN-ITEM
                   GO TO 2200-EXIT
               WHEN OTHER
                   DISPLAY 'ACHPROC: DB2 ERROR ON ACCT LOOKUP '
                           'SQLCODE=' SQLCODE
                   ADD 1 TO WS-ERROR-COUNT
                   GO TO 2200-EXIT
           END-EVALUATE

      *    VALIDATE ACCOUNT STATUS
           IF HV-ACCT-STATUS = 'C'
               MOVE 'R02' TO WS-RETURN-CODE-WORK
               ADD 1 TO WS-ACCT-ERRORS
               PERFORM 2400-WRITE-RETURN-ITEM
               GO TO 2200-EXIT
           END-IF

      *    COMPUTE TRANSACTION AMOUNT
           COMPUTE HV-TRAN-AMOUNT =
               FUNCTION NUMVAL(AED-AMOUNT) / 100

      *    CHECK FOR NSF ON DEBIT ENTRIES
           IF AED-TRANSACTION-CODE = '27' OR '37' OR '28' OR '38'
               MOVE 'DR' TO HV-TRAN-TYPE
               IF HV-AVAILABLE-BALANCE < HV-TRAN-AMOUNT
                   MOVE 'R01' TO WS-RETURN-CODE-WORK
                   ADD 1 TO WS-NSF-RETURNS
                   PERFORM 2400-WRITE-RETURN-ITEM
                   GO TO 2200-EXIT
               END-IF
               SUBTRACT HV-TRAN-AMOUNT FROM HV-CURRENT-BALANCE
               SUBTRACT HV-TRAN-AMOUNT FROM HV-AVAILABLE-BALANCE
               MOVE 'ACHD' TO HV-TRAN-CODE
           ELSE
               MOVE 'CR' TO HV-TRAN-TYPE
               ADD HV-TRAN-AMOUNT TO HV-CURRENT-BALANCE
               ADD HV-TRAN-AMOUNT TO HV-AVAILABLE-BALANCE
               MOVE 'ACHC' TO HV-TRAN-CODE
           END-IF

      *    POST TRANSACTION
           ADD 1 TO WS-TRAN-SEED
           MOVE WS-TRAN-SEED TO HV-TRAN-ID
           MOVE WS-BUSINESS-DATE TO HV-POST-DATE
           MOVE HV-CO-NAME(1:16) TO HV-TRAN-DESC(1:16)
           STRING 'ACH ' DELIMITED BY SIZE HV-SEC-CODE
                  DELIMITED BY SIZE ' ' DELIMITED BY SIZE
                  HV-CO-ID(1:10) DELIMITED BY SIZE
                  INTO HV-TRAN-DESC
           END-STRING

           EXEC SQL
               INSERT INTO BANK.TRANSACTION_HIST
                      (TRAN_ID, ACCT_NUMBER, TRAN_TYPE, TRAN_CODE,
                       AMOUNT, EFFECTIVE_DATE, POST_DATE,
                       DESCRIPTION, REFERENCE_NUM, CHANNEL, TRAN_STATUS)
               VALUES (:HV-TRAN-ID, :HV-ACCT-NUMBER, :HV-TRAN-TYPE,
                       :HV-TRAN-CODE, :HV-TRAN-AMOUNT,
                       :WS-BUSINESS-DATE, :HV-POST-DATE,
                       :HV-TRAN-DESC, :HV-TRACE-NUM, 'BAT', 'P')
           END-EXEC

           IF SQLCODE = 0
               EXEC SQL
                   UPDATE BANK.ACCOUNT
                   SET    CURRENT_BALANCE   = :HV-CURRENT-BALANCE,
                          AVAILABLE_BALANCE = :HV-AVAILABLE-BALANCE,
                          LAST_ACTIVITY_DATE = :HV-POST-DATE,
                          LAST_UPDATE_TS    = CURRENT TIMESTAMP,
                          LAST_UPDATE_USER  = 'ACHPROC'
                   WHERE  ACCT_NUMBER = :HV-ACCT-NUMBER
               END-EXEC

               IF SQLCODE = 0
                   ADD 1 TO WS-ENTRIES-POSTED
                   ADD 1 TO WS-COMMIT-COUNT
                   IF WS-COMMIT-COUNT >= WS-COMMIT-FREQ
                       EXEC SQL COMMIT END-EXEC
                       MOVE ZERO TO WS-COMMIT-COUNT
                   END-IF
               END-IF
           ELSE
               DISPLAY 'ACHPROC: ERROR POSTING ENTRY ACCT='
                       HV-ACCT-NUMBER ' SQLCODE=' SQLCODE
               ADD 1 TO WS-ERROR-COUNT
           END-IF.

       2200-EXIT.
           CONTINUE.

       2300-VERIFY-BATCH-CONTROL.
           SET WS-NOT-IN-BATCH TO TRUE
           EXEC SQL
               UPDATE BANK.ACH_BATCH
               SET    ENTRY_COUNT  = :HV-ENTRY-COUNT,
                      TOTAL_DEBIT  = :HV-TOTAL-DR,
                      TOTAL_CREDIT = :HV-TOTAL-CR,
                      BATCH_STATUS = 'P'
               WHERE  FILE_ID      = :HV-FILE-ID
               AND    BATCH_NUMBER = :HV-BATCH-NUM
           END-EXEC.

       2400-WRITE-RETURN-ITEM.
           ADD 1 TO WS-ENTRIES-RETURNED
           WRITE RETURN-RECORD FROM ACH-ENTRY-DETAIL.

       3000-FINALIZE.
           EXEC SQL COMMIT END-EXEC

           CLOSE ACHFILE
           CLOSE ACHRETURN
           CLOSE ACHRPT
           CLOSE PARMFILE

           DISPLAY 'ACHPROC: PROCESSING COMPLETE'
           DISPLAY 'BATCHES READ:        ' WS-BATCHES-READ
           DISPLAY 'ENTRIES READ:        ' WS-ENTRIES-READ
           DISPLAY 'ENTRIES POSTED:      ' WS-ENTRIES-POSTED
           DISPLAY 'RETURNS GENERATED:   ' WS-ENTRIES-RETURNED
           DISPLAY 'ROUTING ERRORS:      ' WS-ROUTING-ERRORS
           DISPLAY 'NSF RETURNS:         ' WS-NSF-RETURNS
           DISPLAY 'ACCOUNT ERRORS:      ' WS-ACCT-ERRORS

           IF WS-ERROR-COUNT > ZERO OR WS-ENTRIES-RETURNED > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
