      * A SELECT keyed on a WORKING-STORAGE field, like CardDemo's
      * CBEXPORT: the FD record is PIC X(60), the key lives in the
      * record the program WRITEs FROM. GnuCOBOL cannot compile it.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FRNKEY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EXPORT-OUTPUT ASSIGN TO EXPFILE
               ORGANIZATION IS INDEXED
               ACCESS MODE IS SEQUENTIAL
               RECORD KEY IS EXP-SEQ-NUM OF EXP-RECORD
               ALTERNATE RECORD KEY IS EXP-TYPE WITH DUPLICATES
               FILE STATUS IS WS-EXPORT-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  EXPORT-OUTPUT.
       01  EXPORT-OUTPUT-RECORD          PIC X(60).
       WORKING-STORAGE SECTION.
       01  EXP-RECORD.
           05  EXP-SEQ-NUM               PIC 9(9).
           05  EXP-TYPE                  PIC X.
           05  EXP-DATA                  PIC X(50).
       01  WS-EXPORT-STATUS              PIC XX.
           88  WS-EXPORT-OK              VALUE '00'.
       01  WS-WRITTEN                    PIC 9(4) VALUE 0.
       01  WS-RESULT                     PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT EXPORT-OUTPUT
           MOVE 1 TO EXP-SEQ-NUM
           MOVE 'C' TO EXP-TYPE
           MOVE 'ONE' TO EXP-DATA
           WRITE EXPORT-OUTPUT-RECORD FROM EXP-RECORD
           IF WS-EXPORT-OK
               ADD 1 TO WS-WRITTEN
               MOVE 'WRITTEN' TO WS-RESULT
           ELSE
               MOVE 'FAILED' TO WS-RESULT
           END-IF
           CLOSE EXPORT-OUTPUT.
