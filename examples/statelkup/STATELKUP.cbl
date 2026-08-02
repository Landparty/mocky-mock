       IDENTIFICATION DIVISION.
       PROGRAM-ID. STATELKUP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATE-CODE        PIC X(2).
       01  WS-STATE-NAME        PIC X(20).

       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-LOOKUP-STATE
           GOBACK.

       1000-LOOKUP-STATE.
           DISPLAY "WS-STATE-NAME: " WS-STATE-NAME
           EVALUATE WS-STATE-CODE
               WHEN "AZ"
                   MOVE "Arizona" TO WS-STATE-NAME
               WHEN "KY"
                   MOVE "Kentucky" TO WS-STATE-NAME
               WHEN OTHER
                   MOVE "*Undefined*" TO WS-STATE-NAME
           END-EVALUATE.
