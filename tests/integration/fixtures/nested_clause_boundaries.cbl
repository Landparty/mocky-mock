       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTCLB.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT ERR-FILE ASSIGN TO "ERR.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC      PIC X(10).
       FD  ERR-FILE.
       01  ERR-REC     PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-EOF      PIC X VALUE "N".
           88 EOF      VALUE "Y".
       01  WS-COUNT    PIC 9(3) VALUE 0.
       01  WS-ERRS     PIC 9(3) VALUE 0.
       01  WS-RC       PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE OUTPUT ERR-FILE
           PERFORM UNTIL EOF
               READ IN-FILE
                   AT END CALL "EOFLOG" USING WS-COUNT
                          SET EOF TO TRUE
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       CALL "VALIDATE" USING IN-REC WS-RC
                           ON EXCEPTION
                               MOVE IN-REC TO ERR-REC
                               WRITE ERR-REC
                               ADD 1 TO WS-ERRS
                       END-CALL
               END-READ
           END-PERFORM
           CLOSE IN-FILE ERR-FILE
           GOBACK.
