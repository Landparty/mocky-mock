       IDENTIFICATION DIVISION.
       PROGRAM-ID. RATERTE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ACCT-TIER        PIC X(3)    VALUE "STD".
       01  WS-PGM-NAME         PIC X(8)    VALUE SPACES.
       01  WS-BALANCE          PIC 9(7)V99 VALUE 0.
       01  WS-RATE             PIC 9V9999  VALUE 0.
       01  WS-INTEREST         PIC 9(7)V99 VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-SELECT-RATE-PROGRAM
           CALL WS-PGM-NAME USING WS-BALANCE WS-RATE
           COMPUTE WS-INTEREST = WS-BALANCE * WS-RATE
           .

       1000-SELECT-RATE-PROGRAM.
           EVALUATE WS-ACCT-TIER
               WHEN "STD"
                   MOVE "STDRATE" TO WS-PGM-NAME
               WHEN "PRM"
                   MOVE "PRMRATE" TO WS-PGM-NAME
               WHEN "VIP"
                   MOVE "VIPRATE" TO WS-PGM-NAME
               WHEN OTHER
                   MOVE "STDRATE" TO WS-PGM-NAME
           END-EVALUATE
           .
