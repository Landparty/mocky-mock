      *****************************************************************
      * IMS TRANSACTION SEGMENT DEFINITIONS                          *
      * COPYBOOK: TRNSEG                                             *
      * DESCRIPTION: TRNSEG child segment I/O area, IMS Connect     *
      *   message formats, SSA, and shared processing counters.     *
      * HIERARCHY: CUSTDB -> CUSTSEG (root) -> TRNSEG (child)      *
      * USED BY: DEPTIMSM (MPP), DEPTBMP (BMP)                     *
      *****************************************************************
      *
      * TRNSEG SEGMENT I/O AREA - CHILD OF CUSTSEG IN CUSTDB
      *
       01  TRNSEG-IO.
           05  TRAN-CIF-NUMBER      PIC X(10).
           05  TRAN-ACCT-NUMBER     PIC X(12).
           05  TRAN-AMOUNT          PIC S9(11)V99 COMP-3.
           05  TRAN-TYPE            PIC X(02).
               88  TRAN-DEPOSIT     VALUE 'DP'.
               88  TRAN-WITHDRAWAL  VALUE 'WD'.
           05  TRAN-DATE            PIC X(10).
           05  TRAN-CHANNEL         PIC X(04).
               88  TRAN-IMS-CONNECT VALUE 'IMSC'.
               88  TRAN-BATCH       VALUE 'BATC'.
           05  TRAN-STATUS          PIC X(01).
               88  TRAN-POSTED      VALUE 'P'.
           05  TRAN-TIMESTAMP       PIC X(26).
           05  TRAN-FILLER          PIC X(06).
      *
      * IMS CONNECT INPUT MESSAGE - LLZZ PREFIX (4 BYTES) + DATA (46 BYTES)
      *
       01  DEPT-INPUT-MSG.
           05  MSG-LL               PIC S9(04) COMP.
           05  MSG-ZZ               PIC X(02)  VALUE LOW-VALUES.
           05  MSG-CIF-NUMBER       PIC X(10).
           05  MSG-ACCT-NUMBER      PIC X(12).
           05  MSG-AMOUNT-CHAR      PIC X(15).
           05  MSG-TRAN-TYPE        PIC X(02).
           05  MSG-FILLER           PIC X(07).
      *
      * IMS CONNECT OUTPUT REPLY - LLZZ PREFIX (4 BYTES) + DATA (60 BYTES)
      *
       01  DEPT-OUTPUT-MSG.
           05  REPLY-LL             PIC S9(04) COMP.
           05  REPLY-ZZ             PIC X(02)  VALUE LOW-VALUES.
           05  REPLY-RC             PIC X(02).
               88  REPLY-OK         VALUE '00'.
               88  REPLY-CUST-NF    VALUE '04'.
               88  REPLY-INV-INPUT  VALUE '08'.
               88  REPLY-DB-ERROR   VALUE '12'.
           05  REPLY-TEXT           PIC X(50).
           05  REPLY-FILLER         PIC X(08).
      *
      * TRNSEG SSA - UNQUALIFIED, USED ON ISRT UNDER POSITIONED CUSTSEG
      *
       01  SSA-UNQUAL-TRAN         PIC X(09) VALUE 'TRNSEG   '.
      *
      * DEPOSIT PROCESSING COUNTERS (SHARED BY MPP AND BMP)
      *
       01  WS-DEPT-CNTS.
           05  WS-RECS-READ         PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-TRNS-INSERTED     PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-CUST-NOT-FOUND    PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-INVALID-INPUT     PIC 9(05) COMP-3 VALUE ZERO.
           05  WS-DB-ERRORS         PIC 9(05) COMP-3 VALUE ZERO.
