       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDMAIN.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO ORDIN
               FILE STATUS IS WS-ORD-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-IN                PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-ORD-FS               PIC XX.
       01  WS-EOF                  PIC X VALUE "N".
           88  END-OF-ORDERS       VALUE "Y".
       COPY ORDREC.
       01  WS-VAL-RC               PIC 9(2) VALUE 0.
       01  WS-ACCEPTED             PIC 9(5) VALUE 0.
       01  WS-REJECTED             PIC 9(5) VALUE 0.
       01  WS-RUN-DATE             PIC X(8).
       01  WS-AUDIT-PGM            PIC X(8) VALUE "ORDAUD".
       PROCEDURE DIVISION.
       0000-MAIN.
           CALL "DATEUTL" USING WS-RUN-DATE
           OPEN INPUT ORDER-FILE
           PERFORM UNTIL END-OF-ORDERS
               READ ORDER-FILE
                   AT END
                       SET END-OF-ORDERS TO TRUE
                   NOT AT END
                       MOVE ORDER-IN TO ORD-REC
                       PERFORM 1000-PROCESS
               END-READ
           END-PERFORM
           CLOSE ORDER-FILE
           CALL WS-AUDIT-PGM USING WS-ACCEPTED WS-REJECTED
           GOBACK.
       1000-PROCESS.
           MOVE 0 TO WS-VAL-RC
           CALL "ORDVAL" USING ORD-REC WS-VAL-RC
           IF WS-VAL-RC = 0
               CALL "ORDPUB" USING ORD-REC
               ADD 1 TO WS-ACCEPTED
           ELSE
               ADD 1 TO WS-REJECTED
           END-IF.
