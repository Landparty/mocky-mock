       IDENTIFICATION DIVISION.
       PROGRAM-ID. DECLARE.
      *================================================================*
      * Program type: batch program with DECLARATIVES.                 *
      * USE AFTER STANDARD ERROR PROCEDURE on a named file, on every   *
      * INPUT file, and USE GLOBAL for contained programs; the file    *
      * status is examined inside the declarative and the run ends     *
      * cleanly instead of abending with IGZ0035S.                     *
      *================================================================*
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE
               FILE STATUS IS WS-IN-STATUS.
           SELECT OUT-FILE ASSIGN TO OUTFILE
               FILE STATUS IS WS-OUT-STATUS.
           SELECT LOG-FILE ASSIGN TO LOGFILE
               FILE STATUS IS WS-LOG-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE
           RECORDING MODE IS F.
       01  IN-REC                  PIC X(80).
       FD  OUT-FILE
           RECORDING MODE IS F.
       01  OUT-REC                 PIC X(80).
       FD  LOG-FILE
           RECORDING MODE IS F.
       01  LOG-REC                 PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-IN-STATUS            PIC XX.
       01  WS-OUT-STATUS           PIC XX.
       01  WS-LOG-STATUS           PIC XX.
       01  WS-EOF                  PIC X VALUE 'N'.
           88  END-OF-INPUT        VALUE 'Y'.
       01  WS-IO-ERROR             PIC X VALUE 'N'.
           88  IO-ERROR-SEEN       VALUE 'Y'.
       01  WS-COUNT                PIC 9(7) COMP VALUE 0.
       PROCEDURE DIVISION.
       DECLARATIVES.
       IN-FILE-ERROR SECTION.
           USE AFTER STANDARD ERROR PROCEDURE ON IN-FILE.
       IN-FILE-ERROR-PARA.
           DISPLAY 'INFILE I/O ERROR STATUS=' WS-IN-STATUS
           SET IO-ERROR-SEEN TO TRUE
           SET END-OF-INPUT TO TRUE.
       OUT-FILE-ERROR SECTION.
           USE GLOBAL AFTER STANDARD EXCEPTION PROCEDURE ON OUT-FILE.
       OUT-FILE-ERROR-PARA.
           DISPLAY 'OUTFILE I/O ERROR STATUS=' WS-OUT-STATUS
           SET IO-ERROR-SEEN TO TRUE.
       ALL-OUTPUT-ERROR SECTION.
           USE AFTER STANDARD ERROR PROCEDURE ON OUTPUT.
       ALL-OUTPUT-ERROR-PARA.
           MOVE 'OUTPUT FILE ERROR' TO LOG-REC
           WRITE LOG-REC.
       END DECLARATIVES.
       MAIN-LOGIC SECTION.
       0000-MAIN.
           OPEN INPUT IN-FILE OUTPUT OUT-FILE LOG-FILE
           PERFORM UNTIL END-OF-INPUT
               READ IN-FILE
                   AT END SET END-OF-INPUT TO TRUE
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       WRITE OUT-REC FROM IN-REC
               END-READ
           END-PERFORM
           CLOSE IN-FILE OUT-FILE LOG-FILE
           IF IO-ERROR-SEEN
               MOVE 8 TO RETURN-CODE
           END-IF
           DISPLAY 'RECORDS COPIED: ' WS-COUNT
           STOP RUN.
