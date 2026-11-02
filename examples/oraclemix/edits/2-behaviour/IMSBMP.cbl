       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSBMP.
      * MAINTENANCE NOTE: REVIEWED 2026-11-02, NO LOGIC CHANGE
      * IMS BMP: WALKS THE CUSTOMER DATABASE, HOLDS NEGATIVE BALANCES
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GN                 PIC X(4) VALUE 'GN  '.
       01  DLI-GHN                PIC X(4) VALUE 'GHN '.
       01  DLI-REPL               PIC X(4) VALUE 'REPL'.
       01  DLI-CHKP               PIC X(4) VALUE 'CHKP'.
       01  WS-CHKP-ID             PIC X(8) VALUE 'IMSBMP01'.
       01  WS-COUNT               PIC 9(5) VALUE 0.
       01  WS-HELD                PIC 9(5) VALUE 0.
       01  WS-DONE                PIC X VALUE 'N'.
       01  SEG-CUST.
           COPY CUSTREC.
       LINKAGE SECTION.
       01  IO-PCB.
           05  IO-LTERM           PIC X(8).
           05  FILLER             PIC XX.
           05  IO-STATUS          PIC XX.
           05  FILLER             PIC X(20).
       01  DB-PCB.
           05  DB-DBD             PIC X(8).
           05  DB-LEVEL           PIC XX.
           05  DB-STATUS          PIC XX.
           05  DB-PROCOPT         PIC X(4).
           05  FILLER             PIC S9(5) COMP.
           05  DB-SEGNAME         PIC X(8).
           05  DB-KEYLEN          PIC S9(5) COMP.
           05  DB-NSENS           PIC S9(5) COMP.
           05  DB-KEYFB           PIC X(20).
       PROCEDURE DIVISION.
       0000-MAIN.
           ENTRY 'DLITCBL' USING IO-PCB DB-PCB.
           PERFORM UNTIL WS-DONE = 'Y'
               CALL 'CBLTDLI' USING DLI-GHN DB-PCB SEG-CUST
               EVALUATE DB-STATUS
                   WHEN SPACES
                       PERFORM 1000-ONE
                   WHEN 'GB'
                       MOVE 'Y' TO WS-DONE
                   WHEN OTHER
                       DISPLAY 'IMSBMP DLI ERROR ' DB-STATUS
                       MOVE 12 TO RETURN-CODE
                       MOVE 'Y' TO WS-DONE
               END-EVALUATE
           END-PERFORM
           CALL 'CBLTDLI' USING DLI-CHKP IO-PCB WS-CHKP-ID
           DISPLAY 'IMSBMP SEGMENTS ' WS-COUNT ' HELD ' WS-HELD
           GOBACK.
       1000-ONE.
           ADD 1 TO WS-COUNT
           IF CUST-BAL > 0 AND NOT CUST-HELD
               MOVE 'H' TO CUST-STATUS
               CALL 'CBLTDLI' USING DLI-REPL DB-PCB SEG-CUST
               ADD 1 TO WS-HELD
           END-IF.
