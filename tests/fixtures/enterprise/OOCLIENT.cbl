       IDENTIFICATION DIVISION.
       PROGRAM-ID. OOCLIENT.
      *================================================================*
      * Program type: procedural client of OO COBOL / Java classes.    *
      * REPOSITORY, OBJECT REFERENCE data items, INVOKE ... NEW,       *
      * INVOKE with USING/RETURNING, SET obj TO NULL, and the JNI      *
      * environment pointer used to call Java directly.                *
      *================================================================*
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       REPOSITORY.
           CLASS ACCOUNT IS 'com.bank.Account'
           CLASS JSTRING IS 'java.lang.String'.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ACCOUNT              USAGE OBJECT REFERENCE ACCOUNT.
       01  WS-OWNER                PIC X(30) VALUE 'ADA LOVELACE'.
       01  WS-AMOUNT               PIC S9(9)V99 COMP-3 VALUE 250.00.
       01  WS-BALANCE              PIC S9(11)V99 COMP-3.
       01  WS-RC                   PIC S9(4) COMP.
       01  WS-JSTRING              USAGE OBJECT REFERENCE JSTRING.
       01  WS-UTF8-LEN             PIC S9(9) COMP.
       PROCEDURE DIVISION.
       0000-MAIN.
           INVOKE ACCOUNT "create-account"
               USING BY VALUE WS-OWNER
               RETURNING WS-ACCOUNT
           INVOKE WS-ACCOUNT "deposit"
               USING BY VALUE WS-AMOUNT
               RETURNING WS-RC
           IF WS-RC = 0
               INVOKE WS-ACCOUNT "get-balance" RETURNING WS-BALANCE
               DISPLAY 'BALANCE NOW ' WS-BALANCE
           ELSE
               DISPLAY 'DEPOSIT REFUSED RC=' WS-RC
           END-IF
           INVOKE JSTRING NEW RETURNING WS-JSTRING
           IF WS-JSTRING NOT = NULL
               INVOKE WS-JSTRING 'length' RETURNING WS-UTF8-LEN
           END-IF
           SET WS-ACCOUNT TO NULL
           SET WS-JSTRING TO NULL
           GOBACK.
