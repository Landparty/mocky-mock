      *****************************************************************
      * ACH/NACHA RECORD LAYOUTS                                     *
      * COPYBOOK: ACHRECRD                                           *
      * DESCRIPTION: ACH file record structures per NACHA format     *
      * USED BY: ACHPROC, ACHPARSE (PL/I)                           *
      *****************************************************************
      * FILE HEADER RECORD (TYPE 1)
       01  ACH-FILE-HEADER.
           05  AFH-RECORD-TYPE          PIC X(01) VALUE '1'.
           05  AFH-PRIORITY-CODE        PIC X(02) VALUE '01'.
           05  AFH-IMMED-DEST           PIC X(10).
           05  AFH-IMMED-ORIGIN         PIC X(10).
           05  AFH-FILE-CREATION-DATE   PIC X(06).
           05  AFH-FILE-CREATION-TIME   PIC X(04).
           05  AFH-FILE-ID-MODIFIER     PIC X(01).
           05  AFH-RECORD-SIZE          PIC X(03) VALUE '094'.
           05  AFH-BLOCKING-FACTOR      PIC X(02) VALUE '10'.
           05  AFH-FORMAT-CODE          PIC X(01) VALUE '1'.
           05  AFH-DEST-NAME            PIC X(23).
           05  AFH-ORIGIN-NAME          PIC X(23).
           05  AFH-REFERENCE-CODE       PIC X(08).
      *
      * BATCH HEADER RECORD (TYPE 5)
       01  ACH-BATCH-HEADER.
           05  ABH-RECORD-TYPE          PIC X(01) VALUE '5'.
           05  ABH-SERVICE-CLASS        PIC X(03).
               88  ABH-MIXED-DEBITS-CREDITS VALUE '200'.
               88  ABH-CREDITS-ONLY     VALUE '220'.
               88  ABH-DEBITS-ONLY      VALUE '225'.
           05  ABH-COMPANY-NAME         PIC X(16).
           05  ABH-DISCRETIONARY        PIC X(20).
           05  ABH-COMPANY-ID           PIC X(10).
           05  ABH-SEC-CODE             PIC X(03).
               88  ABH-SEC-PPD          VALUE 'PPD'.
               88  ABH-SEC-CCD          VALUE 'CCD'.
               88  ABH-SEC-CTX          VALUE 'CTX'.
               88  ABH-SEC-WEB          VALUE 'WEB'.
           05  ABH-ENTRY-DESCRIPTION    PIC X(10).
           05  ABH-COMPANY-DESC-DATE    PIC X(06).
           05  ABH-EFFECTIVE-DATE       PIC X(06).
           05  ABH-SETTLEMENT-DATE      PIC X(03).
           05  ABH-ORIGINATOR-STATUS    PIC X(01).
           05  ABH-ODFI-ID              PIC X(08).
           05  ABH-BATCH-NUMBER         PIC 9(07).
      *
      * ENTRY DETAIL RECORD (TYPE 6)
       01  ACH-ENTRY-DETAIL.
           05  AED-RECORD-TYPE          PIC X(01) VALUE '6'.
           05  AED-TRANSACTION-CODE     PIC X(02).
               88  AED-CHK-CREDIT       VALUE '22'.
               88  AED-CHK-PRENOTE-CR   VALUE '23'.
               88  AED-CHK-DEBIT        VALUE '27'.
               88  AED-CHK-PRENOTE-DR   VALUE '28'.
               88  AED-SAV-CREDIT       VALUE '32'.
               88  AED-SAV-PRENOTE-CR   VALUE '33'.
               88  AED-SAV-DEBIT        VALUE '37'.
               88  AED-SAV-PRENOTE-DR   VALUE '38'.
           05  AED-RDFI-ID              PIC X(08).
           05  AED-CHECK-DIGIT          PIC X(01).
           05  AED-DFI-ACCT-NUMBER      PIC X(17).
           05  AED-AMOUNT               PIC 9(10).
           05  AED-INDIVIDUAL-ID        PIC X(15).
           05  AED-INDIVIDUAL-NAME      PIC X(22).
           05  AED-DISCRETIONARY        PIC X(02).
           05  AED-ADDENDA-IND          PIC X(01).
           05  AED-TRACE-NUMBER         PIC X(15).
      *
      * BATCH CONTROL RECORD (TYPE 8)
       01  ACH-BATCH-CONTROL.
           05  ABC-RECORD-TYPE          PIC X(01) VALUE '8'.
           05  ABC-SERVICE-CLASS        PIC X(03).
           05  ABC-ENTRY-COUNT          PIC 9(06).
           05  ABC-ENTRY-HASH           PIC 9(10).
           05  ABC-TOTAL-DEBIT          PIC 9(12).
           05  ABC-TOTAL-CREDIT         PIC 9(12).
           05  ABC-COMPANY-ID           PIC X(10).
           05  ABC-MSG-AUTH-CODE        PIC X(19).
           05  ABC-RESERVED             PIC X(06).
           05  ABC-ODFI-ID              PIC X(08).
           05  ABC-BATCH-NUMBER         PIC 9(07).
      *
      * FILE CONTROL RECORD (TYPE 9)
       01  ACH-FILE-CONTROL.
           05  AFC-RECORD-TYPE          PIC X(01) VALUE '9'.
           05  AFC-BATCH-COUNT          PIC 9(06).
           05  AFC-BLOCK-COUNT          PIC 9(06).
           05  AFC-ENTRY-COUNT          PIC 9(08).
           05  AFC-ENTRY-HASH           PIC 9(10).
           05  AFC-TOTAL-DEBIT          PIC 9(12).
           05  AFC-TOTAL-CREDIT         PIC 9(12).
           05  AFC-RESERVED             PIC X(39).
