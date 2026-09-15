       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTED.
      *================================================================*
      * Program type: outer program with nested (contained) programs.  *
      * GLOBAL data shared downward, an IS COMMON sibling callable by  *
      * its siblings, EXTERNAL data shared with separately compiled    *
      * programs, and END PROGRAM stacking three levels deep.          *
      *================================================================*
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SHARED-CONTEXT IS GLOBAL.
           05  WS-RUN-ID           PIC X(8).
           05  WS-ERROR-COUNT      PIC 9(4) COMP VALUE 0.
           05  WS-TRACE-ON         PIC X VALUE 'N'.
               88  TRACE-ON        VALUE 'Y'.
       01  WS-SHOP-TOTALS IS EXTERNAL.
           05  EXT-GRAND-TOTAL     PIC S9(13)V99 COMP-3.
       01  WS-LOCAL-ONLY          PIC X(20).
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE 'RUN00001' TO WS-RUN-ID
           MOVE 'Y' TO WS-TRACE-ON
           CALL 'VALIDATE' USING WS-LOCAL-ONLY
           CALL 'POSTER'
           IF WS-ERROR-COUNT > 0
               MOVE 8 TO RETURN-CODE
           END-IF
           STOP RUN.
      *---------------- contained: sibling used by the others ---------*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOGGER IS COMMON.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-TEXT                 PIC X(40).
       PROCEDURE DIVISION USING LK-TEXT.
       0000-LOG.
           IF TRACE-ON
               DISPLAY WS-RUN-ID ': ' LK-TEXT
           END-IF
           GOBACK.
       END PROGRAM LOGGER.
      *---------------- contained: validation ------------------------*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALIDATE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG                  PIC X(40).
       LINKAGE SECTION.
       01  LK-INPUT                PIC X(20).
       PROCEDURE DIVISION USING LK-INPUT.
       0000-VALIDATE.
           IF LK-INPUT = SPACES
               ADD 1 TO WS-ERROR-COUNT
               MOVE 'EMPTY INPUT' TO WS-MSG
               CALL 'LOGGER' USING WS-MSG
           END-IF
           CALL 'INNER-CHECK'
           GOBACK.
      *---------------- contained inside VALIDATE --------------------*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER-CHECK.
       PROCEDURE DIVISION.
       0000-INNER.
           IF WS-ERROR-COUNT > 10
               DISPLAY 'TOO MANY ERRORS IN ' WS-RUN-ID
           END-IF
           GOBACK.
       END PROGRAM INNER-CHECK.
       END PROGRAM VALIDATE.
      *---------------- contained: posting ---------------------------*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. POSTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG                  PIC X(40) VALUE 'POSTING TOTALS'.
       PROCEDURE DIVISION.
       0000-POST.
           CALL 'LOGGER' USING WS-MSG
           ADD 100 TO EXT-GRAND-TOTAL
           GOBACK.
       END PROGRAM POSTER.
       END PROGRAM NESTED.
