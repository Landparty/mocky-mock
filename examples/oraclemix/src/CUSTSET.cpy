       01  CUSTMAPI.
           02  FILLER             PIC X(12).
           02  CUSTIDL            PIC S9(4) COMP.
           02  CUSTIDF            PIC X.
           02  FILLER REDEFINES CUSTIDF.
               03  CUSTIDA        PIC X.
           02  CUSTIDI            PIC X(6).
           02  CUSTNML            PIC S9(4) COMP.
           02  CUSTNMF            PIC X.
           02  FILLER REDEFINES CUSTNMF.
               03  CUSTNMA        PIC X.
           02  CUSTNMI            PIC X(20).
           02  MSGL               PIC S9(4) COMP.
           02  MSGF               PIC X.
           02  FILLER REDEFINES MSGF.
               03  MSGA           PIC X.
           02  MSGI               PIC X(30).
       01  CUSTMAPO REDEFINES CUSTMAPI.
           02  FILLER             PIC X(12).
           02  FILLER             PIC X(3).
           02  CUSTIDO            PIC X(6).
           02  FILLER             PIC X(3).
           02  CUSTNMO            PIC X(20).
           02  FILLER             PIC X(3).
           02  MSGO               PIC X(30).
