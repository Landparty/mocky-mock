       IDENTIFICATION DIVISION.
       CLASS-ID. ACCOUNT INHERITS BASE.
      *================================================================*
      * Program type: Object-oriented COBOL class definition           *
      * (IBM Enterprise COBOL Java interoperability).                  *
      * REPOSITORY, FACTORY with a factory method, OBJECT with         *
      * instance data and methods, RETURNING, INVOKE SELF/SUPER,       *
      * END METHOD / END OBJECT / END FACTORY / END CLASS.             *
      *================================================================*
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       REPOSITORY.
           CLASS BASE IS 'java.lang.Object'
           CLASS JSTRING IS 'java.lang.String'
           CLASS ACCOUNT IS 'com.bank.Account'.
       FACTORY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  FACT-NEXT-ACCT-NO       PIC 9(10) VALUE 1000000001.
       PROCEDURE DIVISION.
       METHOD-ID. "create-account".
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-OWNER                PIC X(30).
       01  LK-NEW-ACCOUNT          OBJECT REFERENCE ACCOUNT.
       PROCEDURE DIVISION USING BY VALUE LK-OWNER
                          RETURNING LK-NEW-ACCOUNT.
           INVOKE ACCOUNT NEW RETURNING LK-NEW-ACCOUNT
           INVOKE LK-NEW-ACCOUNT "initialize-account"
               USING BY VALUE FACT-NEXT-ACCT-NO LK-OWNER
           ADD 1 TO FACT-NEXT-ACCT-NO
           GOBACK.
       END METHOD "create-account".
       END FACTORY.
       OBJECT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  OBJ-ACCT-NO             PIC 9(10).
       01  OBJ-OWNER               PIC X(30).
       01  OBJ-BALANCE             PIC S9(11)V99 COMP-3 VALUE 0.
       01  OBJ-STATUS              PIC X VALUE 'A'.
           88  OBJ-ACTIVE          VALUE 'A'.
           88  OBJ-FROZEN          VALUE 'F'.
       PROCEDURE DIVISION.
       METHOD-ID. "initialize-account".
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-ACCT-NO              PIC 9(10).
       01  LK-OWNER                PIC X(30).
       PROCEDURE DIVISION USING BY VALUE LK-ACCT-NO LK-OWNER.
           MOVE LK-ACCT-NO TO OBJ-ACCT-NO
           MOVE LK-OWNER TO OBJ-OWNER
           MOVE ZERO TO OBJ-BALANCE
           SET OBJ-ACTIVE TO TRUE
           GOBACK.
       END METHOD "initialize-account".
       METHOD-ID. "deposit".
       DATA DIVISION.
       LOCAL-STORAGE SECTION.
       01  LS-OLD-BALANCE          PIC S9(11)V99 COMP-3.
       LINKAGE SECTION.
       01  LK-AMOUNT               PIC S9(9)V99 COMP-3.
       01  LK-RC                   PIC S9(4) COMP.
       PROCEDURE DIVISION USING BY VALUE LK-AMOUNT RETURNING LK-RC.
           IF OBJ-FROZEN OR LK-AMOUNT <= 0
               MOVE 8 TO LK-RC
           ELSE
               MOVE OBJ-BALANCE TO LS-OLD-BALANCE
               ADD LK-AMOUNT TO OBJ-BALANCE
               INVOKE SELF "audit" USING BY VALUE LS-OLD-BALANCE
               MOVE 0 TO LK-RC
           END-IF
           GOBACK.
       END METHOD "deposit".
       METHOD-ID. "audit".
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-OLD-BALANCE          PIC S9(11)V99 COMP-3.
       PROCEDURE DIVISION USING BY VALUE LK-OLD-BALANCE.
           DISPLAY 'ACCOUNT ' OBJ-ACCT-NO ' ' LK-OLD-BALANCE
                   ' -> ' OBJ-BALANCE
           GOBACK.
       END METHOD "audit".
       METHOD-ID. "get-balance".
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-BALANCE              PIC S9(11)V99 COMP-3.
       PROCEDURE DIVISION RETURNING LK-BALANCE.
           MOVE OBJ-BALANCE TO LK-BALANCE
           GOBACK.
       END METHOD "get-balance".
       END OBJECT.
       END CLASS ACCOUNT.
