       IDENTIFICATION DIVISION.
       PROGRAM-ID. TAXFILE.
      * Adapted from the cobol-check wiki's own taxpayer-update-file
      * example: validates a postal code after a file read, and reports
      * an error code when the file itself fails to open.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TAXPAYER-FILE ASSIGN TO "TAX.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-TAXPAYER-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  TAXPAYER-FILE.
       01  TAXPAYER-REC.
           05  TP-TAXPAYER-ID     PIC X(9).
           05  TP-POSTCODE        PIC X(10).

       WORKING-STORAGE SECTION.
       01  WS-TAXPAYER-STATUS     PIC X(2).
       01  WS-ERROR-CODE          PIC X(9) VALUE SPACES.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM OPEN-FILE.
           IF WS-ERROR-CODE = SPACES
               PERFORM VALIDATE-IN-REC
           END-IF.
           PERFORM CLOSE-FILE.

       OPEN-FILE.
           OPEN INPUT TAXPAYER-FILE.
           IF WS-TAXPAYER-STATUS NOT = "00"
               MOVE "TUFNOTFND" TO WS-ERROR-CODE
           END-IF.

       VALIDATE-IN-REC.
           READ TAXPAYER-FILE.
           IF TP-POSTCODE = SPACES
               MOVE "TUFNOPOST" TO WS-ERROR-CODE
           END-IF.

       CLOSE-FILE.
           CLOSE TAXPAYER-FILE.
