      *****************************************************************
      * IMS PCB MASK DEFINITIONS                                     *
      * COPYBOOK: IMSPCB                                             *
      * DESCRIPTION: IMS Program Communication Block masks           *
      * USED BY: LOANPMT, programs using IMS DL/I                   *
      *****************************************************************
       01  CUSTOMER-PCB-MASK.
           05  CPCB-DBD-NAME            PIC X(08).
           05  CPCB-SEG-LEVEL           PIC X(02).
           05  CPCB-STATUS-CODE         PIC X(02).
               88  CPCB-SUCCESS         VALUE '  '.
               88  CPCB-NOT-FOUND       VALUE 'GE'.
               88  CPCB-END-OF-DB       VALUE 'GB'.
               88  CPCB-DUPLICATE       VALUE 'II'.
           05  CPCB-PROC-OPTIONS        PIC X(04).
           05  CPCB-RESERVED            PIC S9(05) COMP.
           05  CPCB-SEG-NAME            PIC X(08).
           05  CPCB-KEY-LENGTH          PIC S9(05) COMP.
           05  CPCB-NUM-SENS-SEGS       PIC S9(05) COMP.
           05  CPCB-KEY-FEEDBACK        PIC X(30).
      *
       01  LOAN-PCB-MASK.
           05  LPCB-DBD-NAME            PIC X(08).
           05  LPCB-SEG-LEVEL           PIC X(02).
           05  LPCB-STATUS-CODE         PIC X(02).
               88  LPCB-SUCCESS         VALUE '  '.
               88  LPCB-NOT-FOUND       VALUE 'GE'.
               88  LPCB-END-OF-DB       VALUE 'GB'.
               88  LPCB-SEG-NOT-FOUND   VALUE 'GE'.
           05  LPCB-PROC-OPTIONS        PIC X(04).
           05  LPCB-RESERVED            PIC S9(05) COMP.
           05  LPCB-SEG-NAME            PIC X(08).
           05  LPCB-KEY-LENGTH          PIC S9(05) COMP.
           05  LPCB-NUM-SENS-SEGS       PIC S9(05) COMP.
           05  LPCB-KEY-FEEDBACK        PIC X(30).
      *
       01  IMS-IO-AREA                  PIC X(500).
      *
       01  DLI-FUNCTIONS.
           05  DLI-GU                   PIC X(04) VALUE 'GU  '.
           05  DLI-GN                   PIC X(04) VALUE 'GN  '.
           05  DLI-GNP                  PIC X(04) VALUE 'GNP '.
           05  DLI-GHU                  PIC X(04) VALUE 'GHU '.
           05  DLI-GHN                  PIC X(04) VALUE 'GHN '.
           05  DLI-ISRT                 PIC X(04) VALUE 'ISRT'.
           05  DLI-REPL                 PIC X(04) VALUE 'REPL'.
           05  DLI-DLET                 PIC X(04) VALUE 'DLET'.
           05  DLI-CHKP                 PIC X(04) VALUE 'CHKP'.
      *
       01  SSA-CUSTOMER.
           05  FILLER                   PIC X(09) VALUE 'CUSTSEG ('.
           05  SSA-CUST-KEY-NAME        PIC X(10) VALUE 'CUSTID   ='.
           05  SSA-CUST-KEY-VALUE       PIC X(10).
           05  FILLER                   PIC X(01) VALUE ')'.
      *
       01  SSA-LOAN.
           05  FILLER                   PIC X(09) VALUE 'LOANSEG ('.
           05  SSA-LOAN-KEY-NAME        PIC X(10) VALUE 'LOANNUM  ='.
           05  SSA-LOAN-KEY-VALUE       PIC X(12).
           05  FILLER                   PIC X(01) VALUE ')'.
      *
       01  SSA-UNQUAL-CUST             PIC X(09) VALUE 'CUSTSEG  '.
       01  SSA-UNQUAL-LOAN             PIC X(09) VALUE 'LOANSEG  '.
