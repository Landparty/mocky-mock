       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNTAB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TAB.
           05 WS-ENT    PIC X(8) OCCURS 2 TIMES.
       01  WS-I         PIC 9 VALUE 1.
       01  WS-ARG       PIC X(4) VALUE "X".
       PROCEDURE DIVISION.
       P2.
           MOVE "OTHER" TO WS-ENT(1)
           MOVE "DYNSUB" TO WS-ENT(2)
           MOVE 2 TO WS-I
           CALL WS-ENT(WS-I) USING WS-ARG.
