       IDENTIFICATION DIVISION.
       PROGRAM-ID. CTRRPT.
      *****************************************************************
      * CURRENCY TRANSACTION REPORT (CTR) PROGRAM                   *
      * DESCRIPTION: BSA/AML regulatory compliance program. Detects  *
      *   cash transactions at or above $10,000 threshold, creates  *
      *   FinCEN CTR records, and flags suspicious activity (SAR).   *
      *   Aggregates multiple same-day transactions per customer.    *
      * INPUT:  DB2 BANK.TRANSACTION_HIST (today's transactions)     *
      *         DB2 BANK.CUSTOMER          (customer info)           *
      * OUTPUT: DB2 BANK.REGULATORY_RPT (CTR/SAR records)           *
      *         CTRRPT   - CTR activity report                       *
      *         CTRFILE  - FinCEN file for regulatory submission     *
      * DB2 PLAN: CTRPLAN                                            *
      * FREQUENCY: Daily (must file within 15 days of transaction)  *
      *****************************************************************

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CTRRPT  ASSIGN TO CTRRPTDD
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT CTRFILE ASSIGN TO CTRFILE
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-CTR-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  CTRRPT
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  CTRRPT-RECORD             PIC X(133).

       FD  CTRFILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  CTR-OUTPUT-RECORD         PIC X(200).

       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.

       COPY WSCOMMON.
       COPY ERRORCD.

       01  WS-CTR-STATUS             PIC X(02).
           88  WS-CTR-OK             VALUE '00'.

       01  WS-FATAL-ERROR-FLAG       PIC X(01) VALUE 'N'.
           88  FATAL-ERROR-FOUND     VALUE 'Y'.

      *-----------------------------------------------------------------
      * DB2 HOST VARIABLES
      *-----------------------------------------------------------------
       01  WS-CTR-HV.
           05  HV-CIF-NUMBER         PIC X(10).
           05  HV-ACCT-NUMBER        PIC X(12).
           05  HV-FIRST-NAME         PIC X(25).
           05  HV-LAST-NAME          PIC X(30).
           05  HV-SSN                PIC X(09).
           05  HV-ADDR1              PIC X(40).
           05  HV-CITY               PIC X(25).
           05  HV-STATE              PIC X(02).
           05  HV-ZIP                PIC X(10).
           05  HV-DOB                PIC X(10).
           05  HV-TOTAL-CASH-IN      PIC S9(15)V99 COMP-3.
           05  HV-TOTAL-CASH-OUT     PIC S9(15)V99 COMP-3.
           05  HV-TRAN-COUNT         PIC S9(9)      COMP.
           05  HV-POST-DATE          PIC X(10).
           05  HV-CTR-THRESHOLD      PIC S9(11)V99 COMP-3.
           05  HV-RPT-TYPE           PIC X(04).

      *-----------------------------------------------------------------
      * CTR THRESHOLD CURSOR - CUSTOMERS EXCEEDING $10,000
      *-----------------------------------------------------------------
           EXEC SQL
               DECLARE CTR_CURSOR CURSOR FOR
               SELECT   T.ACCT_NUMBER,
                        A.CIF_NUMBER,
                        C.FIRST_NAME,
                        C.LAST_NAME,
                        C.SSN,
                        C.ADDR_LINE1,
                        C.CITY,
                        C.STATE,
                        C.ZIP,
                        CHAR(C.DATE_OF_BIRTH),
                        SUM(CASE WHEN T.TRAN_TYPE = 'CR' AND
                                 T.TRAN_CODE IN ('DEP ','XFI ')
                                 THEN T.AMOUNT ELSE 0 END)
                            AS CASH_IN,
                        SUM(CASE WHEN T.TRAN_TYPE = 'DR' AND
                                 T.TRAN_CODE IN ('WDL ','XFO ')
                                 THEN T.AMOUNT ELSE 0 END)
                            AS CASH_OUT,
                        COUNT(*) AS TRAN_CNT
               FROM     BANK.TRANSACTION_HIST T
               INNER JOIN BANK.ACCOUNT A
                        ON T.ACCT_NUMBER = A.ACCT_NUMBER
               INNER JOIN BANK.CUSTOMER C
                        ON A.CIF_NUMBER = C.CIF_NUMBER
               WHERE    T.POST_DATE  = :HV-POST-DATE
               AND      T.TRAN_STATUS = 'P'
               AND      T.CHANNEL    IN ('BRN','ATM')
               GROUP BY T.ACCT_NUMBER, A.CIF_NUMBER,
                        C.FIRST_NAME, C.LAST_NAME, C.SSN,
                        C.ADDR_LINE1, C.CITY, C.STATE, C.ZIP,
                        C.DATE_OF_BIRTH
               HAVING   (SUM(CASE WHEN T.TRAN_TYPE = 'CR' AND
                                  T.TRAN_CODE IN ('DEP ','XFI ')
                                  THEN T.AMOUNT ELSE 0 END) >= 10000.00
                        OR
                         SUM(CASE WHEN T.TRAN_TYPE = 'DR' AND
                                  T.TRAN_CODE IN ('WDL ','XFO ')
                                  THEN T.AMOUNT ELSE 0 END) >= 10000.00)
           END-EXEC.

      *-----------------------------------------------------------------
      * CTR FORM RECORD (FINCEN FORMAT - SIMPLIFIED)
      *-----------------------------------------------------------------
       01  WS-CTR-FORM.
           05  WS-CTR-FORM-TYPE      PIC X(04) VALUE 'CTR '.
           05  WS-CTR-BANK-NAME      PIC X(40)
               VALUE 'FIRST NATIONAL BANK                     '.
           05  WS-CTR-BANK-EIN       PIC X(09) VALUE '123456789'.
           05  WS-CTR-CUSTOMER-NAME   PIC X(56).
           05  WS-CTR-SSN            PIC X(09).
           05  WS-CTR-ADDR           PIC X(40).
           05  WS-CTR-ACCT           PIC X(12).
           05  WS-CTR-CASH-IN        PIC 9(11)V99.
           05  WS-CTR-CASH-OUT       PIC 9(11)V99.
           05  WS-CTR-DATE           PIC X(10).
           05  FILLER                PIC X(07).

      *-----------------------------------------------------------------
      * REPORT LINE
      *-----------------------------------------------------------------
       01  WS-CTR-HDR1.
           05  FILLER PIC X(50) VALUE
               'FIRST NATIONAL BANK - CURRENCY TRANSACTION REPORT'.
           05  FILLER PIC X(30) VALUE ' - DATE: '.
           05  WS-CTR-HDR1-DATE PIC X(10).
           05  FILLER PIC X(43) VALUE SPACES.

       01  WS-CTR-COLHDR.
           05  FILLER PIC X(11) VALUE 'ACCOUNT    '.
           05  FILLER PIC X(11) VALUE 'CIF        '.
           05  FILLER PIC X(31) VALUE 'CUSTOMER NAME                  '.
           05  FILLER PIC X(16) VALUE '   CASH IN      '.
           05  FILLER PIC X(16) VALUE '   CASH OUT     '.
           05  FILLER PIC X(06) VALUE 'CNT   '.
           05  FILLER PIC X(06) VALUE 'ACTION'.

       01  WS-CTR-DETAIL.
           05  WS-CTRD-ACCT          PIC X(12).
           05  FILLER                PIC X(01) VALUE SPACE.
           05  WS-CTRD-CIF           PIC X(10).
           05  FILLER                PIC X(01) VALUE SPACE.
           05  WS-CTRD-NAME          PIC X(30).
           05  FILLER                PIC X(01) VALUE SPACE.
           05  WS-CTRD-CASH-IN       PIC ZZZ,ZZZ,ZZZ,ZZ9.99.
           05  FILLER                PIC X(01) VALUE SPACE.
           05  WS-CTRD-CASH-OUT      PIC ZZZ,ZZZ,ZZZ,ZZ9.99.
           05  FILLER                PIC X(02) VALUE SPACES.
           05  WS-CTRD-COUNT         PIC ZZZ9.
           05  FILLER                PIC X(02) VALUE SPACES.
           05  WS-CTRD-ACTION        PIC X(12).

      *-----------------------------------------------------------------
      * COUNTERS
      *-----------------------------------------------------------------
       01  WS-CTR-CNTS.
           05  WS-CTRS-FILED        PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-SARS-FLAGGED      PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-CTR-ERRORS        PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-TOTAL-CASH-IN     PIC S9(15)V99 COMP-3 VALUE ZERO.
           05  WS-TOTAL-CASH-OUT    PIC S9(15)V99 COMP-3 VALUE ZERO.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-DETECT-CTR-TRANSACTIONS
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-INITIALIZE.
           DISPLAY 'CTRRPT: CTR DETECTION PROCESSING STARTED'
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
           STRING WS-CURRENT-YEAR DELIMITED BY SIZE '-'
                  DELIMITED BY SIZE WS-CURRENT-MONTH
                  DELIMITED BY SIZE '-' DELIMITED BY SIZE
                  WS-CURRENT-DAY DELIMITED BY SIZE
                  INTO WS-BUSINESS-DATE
           END-STRING

           MOVE WS-BUSINESS-DATE TO HV-POST-DATE
           MOVE WS-BUSINESS-DATE TO WS-CTR-HDR1-DATE

           OPEN OUTPUT CTRRPT
           OPEN OUTPUT CTRFILE

           WRITE CTRRPT-RECORD FROM WS-CTR-HDR1
           WRITE CTRRPT-RECORD FROM WS-CTR-COLHDR

           EXEC SQL OPEN CTR_CURSOR END-EXEC
           IF SQLCODE NOT = 0
               DISPLAY 'CTRRPT: CANNOT OPEN CTR_CURSOR SQLCODE='
                       SQLCODE
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF.

       2000-DETECT-CTR-TRANSACTIONS.
           PERFORM 2100-FETCH-CTR-TRANSACTION
               UNTIL SQLCODE = +100 OR FATAL-ERROR-FOUND.

       2100-FETCH-CTR-TRANSACTION.
           EXEC SQL
               FETCH CTR_CURSOR
               INTO  :HV-ACCT-NUMBER,
                     :HV-CIF-NUMBER,
                     :HV-FIRST-NAME,
                     :HV-LAST-NAME,
                     :HV-SSN,
                     :HV-ADDR1,
                     :HV-CITY,
                     :HV-STATE,
                     :HV-ZIP,
                     :HV-DOB,
                     :HV-TOTAL-CASH-IN,
                     :HV-TOTAL-CASH-OUT,
                     :HV-TRAN-COUNT
           END-EXEC

           EVALUATE SQLCODE
               WHEN 0
                   ADD 1 TO WS-RECORD-COUNT
                   PERFORM 2200-CREATE-CTR-RECORD
               WHEN +100
                   CONTINUE
               WHEN OTHER
                   DISPLAY 'CTRRPT: FETCH ERROR SQLCODE=' SQLCODE
                   SET FATAL-ERROR-FOUND TO TRUE
           END-EVALUATE.

       2200-CREATE-CTR-RECORD.
      *    CHECK FOR STRUCTURING PATTERN (SAR TRIGGER)
           IF HV-TRAN-COUNT > 3 AND
              (HV-TOTAL-CASH-IN >= 9000 AND
               HV-TOTAL-CASH-IN < 10000)
               MOVE 'SAR ' TO HV-RPT-TYPE
               ADD 1 TO WS-SARS-FLAGGED
               DISPLAY 'CTRRPT: POSSIBLE STRUCTURING DETECTED '
                       'ACCT=' HV-ACCT-NUMBER
                       ' AMOUNT=' HV-TOTAL-CASH-IN
           ELSE
               MOVE 'CTR ' TO HV-RPT-TYPE
           END-IF

      *    INSERT REGULATORY REPORT RECORD
           EXEC SQL
               INSERT INTO BANK.REGULATORY_RPT
                      (RPT_TYPE, CIF_NUMBER, ACCT_NUMBER,
                       TRAN_DATE, TRAN_AMOUNT, TRAN_COUNT,
                       RPT_STATUS, CREATED_BY)
               VALUES (:HV-RPT-TYPE, :HV-CIF-NUMBER, :HV-ACCT-NUMBER,
                       :HV-POST-DATE, :HV-TOTAL-CASH-IN,
                       :HV-TRAN-COUNT, 'P', 'CTRRPT')
           END-EXEC

           IF SQLCODE = 0
               ADD 1 TO WS-CTRS-FILED
               ADD HV-TOTAL-CASH-IN  TO WS-TOTAL-CASH-IN
               ADD HV-TOTAL-CASH-OUT TO WS-TOTAL-CASH-OUT
           ELSE
               ADD 1 TO WS-CTR-ERRORS
           END-IF

      *    BUILD FINCEN OUTPUT RECORD
           STRING HV-FIRST-NAME DELIMITED BY SPACE ' '
                  DELIMITED BY SIZE HV-LAST-NAME DELIMITED BY SPACE
                  INTO WS-CTR-CUSTOMER-NAME
           MOVE HV-SSN              TO WS-CTR-SSN
           MOVE HV-ADDR1            TO WS-CTR-ADDR
           MOVE HV-ACCT-NUMBER      TO WS-CTR-ACCT
           MOVE HV-TOTAL-CASH-IN    TO WS-CTR-CASH-IN
           MOVE HV-TOTAL-CASH-OUT   TO WS-CTR-CASH-OUT
           MOVE WS-BUSINESS-DATE    TO WS-CTR-DATE
           WRITE CTR-OUTPUT-RECORD FROM WS-CTR-FORM

      *    WRITE REPORT LINE
           MOVE HV-ACCT-NUMBER TO WS-CTRD-ACCT
           MOVE HV-CIF-NUMBER  TO WS-CTRD-CIF
           STRING HV-FIRST-NAME DELIMITED BY SPACE ' '
                  DELIMITED BY SIZE HV-LAST-NAME DELIMITED BY SPACE
                  INTO WS-CTRD-NAME
           MOVE HV-TOTAL-CASH-IN    TO WS-CTRD-CASH-IN
           MOVE HV-TOTAL-CASH-OUT   TO WS-CTRD-CASH-OUT
           MOVE HV-TRAN-COUNT       TO WS-CTRD-COUNT
           MOVE HV-RPT-TYPE         TO WS-CTRD-ACTION
           WRITE CTRRPT-RECORD FROM WS-CTR-DETAIL

           ADD 1 TO WS-COMMIT-COUNT
           IF WS-COMMIT-COUNT >= WS-COMMIT-FREQ
               EXEC SQL COMMIT END-EXEC
               MOVE ZERO TO WS-COMMIT-COUNT
           END-IF.

       3000-FINALIZE.
           EXEC SQL COMMIT END-EXEC
           EXEC SQL CLOSE CTR_CURSOR END-EXEC

           CLOSE CTRRPT CTRFILE

           DISPLAY 'CTRRPT: CTR REPORTING COMPLETE'
           DISPLAY 'CTR RECORDS FILED:    ' WS-CTRS-FILED
           DISPLAY 'SAR FLAGS:            ' WS-SARS-FLAGGED
           DISPLAY 'TOTAL CASH IN:        ' WS-TOTAL-CASH-IN
           DISPLAY 'TOTAL CASH OUT:       ' WS-TOTAL-CASH-OUT
           DISPLAY 'ERRORS:               ' WS-CTR-ERRORS

           IF WS-CTR-ERRORS > ZERO
               MOVE 4 TO RETURN-CODE
           ELSE
               MOVE ZERO TO RETURN-CODE
           END-IF.
