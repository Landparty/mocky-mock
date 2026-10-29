       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMEKIND.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REF-FILE ASSIGN TO "REF.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC      PIC X(10).
       FD  REF-FILE.
       01  REF-REC     PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-EOF      PIC X VALUE "N".
           88 EOF      VALUE "Y".
       01  WS-COUNT    PIC 9(3) VALUE 0.
       01  WS-ERRS     PIC 9(3) VALUE 0.
       01  WS-NOREF    PIC 9(3) VALUE 0.
       01  WS-RC       PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE REF-FILE
           PERFORM UNTIL EOF
               READ IN-FILE
                   AT END
                       SET EOF TO TRUE
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       READ REF-FILE
                           AT END
                               ADD 1 TO WS-NOREF
                       END-READ
                       CALL "VALIDATE" USING IN-REC WS-RC
                           ON EXCEPTION
                               CALL "ERRLOG" USING IN-REC
                               END-CALL
                               ADD 1 TO WS-ERRS
                       END-CALL
               END-READ
           END-PERFORM
           CLOSE IN-FILE REF-FILE
           GOBACK.
