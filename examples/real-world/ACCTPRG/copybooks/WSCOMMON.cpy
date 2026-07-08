      *****************************************************************
      * COMMON WORKING STORAGE VARIABLES                             *
      * COPYBOOK: WSCOMMON                                           *
      * DESCRIPTION: Shared working storage fields for banking       *
      * USED BY: All COBOL programs                                  *
      *****************************************************************
       01  WS-COMMON-FIELDS.
           05  WS-RETURN-CODE            PIC S9(4) COMP VALUE ZERO.
           05  WS-ERROR-CODE             PIC X(04) VALUE SPACES.
           05  WS-ERROR-MESSAGE          PIC X(80) VALUE SPACES.
           05  WS-RECORD-COUNT           PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-ERROR-COUNT            PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-PROCESS-COUNT          PIC 9(09) COMP-3 VALUE ZERO.
           05  WS-CURRENT-DATE-TIME.
               10  WS-CURRENT-DATE.
                   15  WS-CURRENT-YEAR   PIC 9(04).
                   15  WS-CURRENT-MONTH  PIC 9(02).
                   15  WS-CURRENT-DAY    PIC 9(02).
               10  WS-CURRENT-TIME.
                   15  WS-CURRENT-HOUR   PIC 9(02).
                   15  WS-CURRENT-MIN    PIC 9(02).
                   15  WS-CURRENT-SEC    PIC 9(02).
           05  WS-EOF-FLAG               PIC X(01) VALUE 'N'.
               88  WS-EOF                VALUE 'Y'.
               88  WS-NOT-EOF            VALUE 'N'.
      *
       01  WS-BANKING-DATES.
           05  WS-BUSINESS-DATE          PIC X(10).
           05  WS-PREVIOUS-BUS-DATE      PIC X(10).
           05  WS-NEXT-BUS-DATE          PIC X(10).
           05  WS-MONTH-END-FLAG         PIC X(01) VALUE 'N'.
               88  WS-IS-MONTH-END       VALUE 'Y'.
               88  WS-NOT-MONTH-END      VALUE 'N'.
           05  WS-QUARTER-END-FLAG       PIC X(01) VALUE 'N'.
               88  WS-IS-QUARTER-END     VALUE 'Y'.
               88  WS-NOT-QUARTER-END    VALUE 'N'.
           05  WS-YEAR-END-FLAG          PIC X(01) VALUE 'N'.
               88  WS-IS-YEAR-END        VALUE 'Y'.
               88  WS-NOT-YEAR-END       VALUE 'N'.
      *
       01  WS-DB2-FIELDS.
           05  WS-DB2-SUBSYSTEM          PIC X(04) VALUE 'DB2P'.
           05  WS-COMMIT-FREQ            PIC 9(05) COMP-3 VALUE 500.
           05  WS-COMMIT-COUNT           PIC 9(05) COMP-3 VALUE ZERO.
      *
       01  WS-DISPLAY-FIELDS.
           05  WS-DISP-SQLCODE           PIC -(9)9.
           05  WS-DISP-COUNT             PIC Z,ZZZ,ZZ9.
           05  WS-DISP-AMOUNT            PIC Z,ZZZ,ZZZ,ZZ9.99-.
           05  WS-DISP-RATE              PIC Z9.999999.
