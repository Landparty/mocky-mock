      *****************************************************************
      * BANKING ERROR CODE DEFINITIONS                               *
      * COPYBOOK: ERRORCD                                            *
      * DESCRIPTION: Standard error codes for banking operations     *
      * USED BY: All COBOL programs                                  *
      *****************************************************************
       01  WS-BANKING-ERROR-CODES.
           05  ERR-SUCCESS               PIC X(04) VALUE '0000'.
           05  ERR-ACCT-NOT-FOUND        PIC X(04) VALUE 'E001'.
           05  ERR-ACCT-CLOSED           PIC X(04) VALUE 'E002'.
           05  ERR-ACCT-FROZEN           PIC X(04) VALUE 'E003'.
           05  ERR-ACCT-DORMANT          PIC X(04) VALUE 'E004'.
           05  ERR-INSUFFICIENT-FUNDS    PIC X(04) VALUE 'E005'.
           05  ERR-OVERDRAFT-EXCEEDED    PIC X(04) VALUE 'E006'.
           05  ERR-INVALID-AMOUNT        PIC X(04) VALUE 'E007'.
           05  ERR-INVALID-TRAN-CODE     PIC X(04) VALUE 'E008'.
           05  ERR-HOLD-ON-ACCOUNT       PIC X(04) VALUE 'E009'.
           05  ERR-CUST-NOT-FOUND        PIC X(04) VALUE 'E010'.
           05  ERR-LOAN-NOT-FOUND        PIC X(04) VALUE 'E011'.
           05  ERR-LOAN-PAID-OFF         PIC X(04) VALUE 'E012'.
           05  ERR-LOAN-DEFAULTED        PIC X(04) VALUE 'E013'.
           05  ERR-INVALID-ROUTING       PIC X(04) VALUE 'E014'.
           05  ERR-ACH-REJECT            PIC X(04) VALUE 'E015'.
           05  ERR-GL-OUT-OF-BAL         PIC X(04) VALUE 'E016'.
           05  ERR-DB2-ERROR             PIC X(04) VALUE 'E050'.
           05  ERR-IMS-ERROR             PIC X(04) VALUE 'E051'.
           05  ERR-FILE-ERROR            PIC X(04) VALUE 'E052'.
           05  ERR-PROGRAM-ERROR         PIC X(04) VALUE 'E099'.
      *
       01  WS-ACH-RETURN-CODES.
           05  ACH-R01                   PIC X(03) VALUE 'R01'.
           05  ACH-R01-DESC              PIC X(30)
               VALUE 'INSUFFICIENT FUNDS            '.
           05  ACH-R02                   PIC X(03) VALUE 'R02'.
           05  ACH-R02-DESC              PIC X(30)
               VALUE 'ACCOUNT CLOSED                '.
           05  ACH-R03                   PIC X(03) VALUE 'R03'.
           05  ACH-R03-DESC              PIC X(30)
               VALUE 'NO ACCOUNT/UNABLE TO LOCATE   '.
           05  ACH-R04                   PIC X(03) VALUE 'R04'.
           05  ACH-R04-DESC              PIC X(30)
               VALUE 'INVALID ACCOUNT NUMBER        '.
           05  ACH-R06                   PIC X(03) VALUE 'R06'.
           05  ACH-R06-DESC              PIC X(30)
               VALUE 'RETURNED PER ODFI REQUEST     '.
           05  ACH-R08                   PIC X(03) VALUE 'R08'.
           05  ACH-R08-DESC              PIC X(30)
               VALUE 'PAYMENT STOPPED               '.
           05  ACH-R10                   PIC X(03) VALUE 'R10'.
           05  ACH-R10-DESC              PIC X(30)
               VALUE 'CUSTOMER ADVISES NOT AUTHORIZED'.
           05  ACH-R29                   PIC X(03) VALUE 'R29'.
           05  ACH-R29-DESC              PIC X(30)
               VALUE 'CORPORATE ENTRY NOT AUTHORIZED'.
