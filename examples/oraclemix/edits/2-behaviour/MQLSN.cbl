       IDENTIFICATION DIVISION.
       PROGRAM-ID. MQLSN.
      * MAINTENANCE NOTE: REVIEWED 2026-11-02, NO LOGIC CHANGE
      * MQ LISTENER: GET BALANCE REQUESTS, PUT REPLIES
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-HCONN               PIC S9(9) BINARY VALUE 0.
       01  WS-HIN                 PIC S9(9) BINARY.
       01  WS-HOUT                PIC S9(9) BINARY.
       01  WS-OPTIONS             PIC S9(9) BINARY.
       01  WS-COMPCODE            PIC S9(9) BINARY.
       01  WS-REASON              PIC S9(9) BINARY.
       01  WS-BUFLEN              PIC S9(9) BINARY VALUE 40.
       01  WS-DATALEN             PIC S9(9) BINARY.
       01  WS-OD-IN               PIC X(168).
       01  WS-OD-OUT              PIC X(168).
       01  WS-MD                  PIC X(324).
       01  WS-GMO                 PIC X(112).
       01  WS-PMO                 PIC X(152).
       01  WS-REQUEST.
           05  RQ-CUST-ID         PIC 9(6).
           05  RQ-AMOUNT          PIC 9(7)V99.
           05  FILLER             PIC X(25).
       01  WS-REPLY.
           05  RP-CUST-ID         PIC 9(6).
           05  RP-FEE             PIC 9(5)V99.
           05  RP-CODE            PIC X(2).
       01  WS-COUNT               PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE 8193 TO WS-OPTIONS
           CALL 'MQOPEN' USING WS-HCONN WS-OD-IN WS-OPTIONS
                               WS-HIN WS-COMPCODE WS-REASON
           IF WS-COMPCODE NOT = 0
               DISPLAY 'MQLSN OPEN FAILED ' WS-REASON
               MOVE 12 TO RETURN-CODE
               GOBACK
           END-IF
           MOVE 16 TO WS-OPTIONS
           CALL 'MQOPEN' USING WS-HCONN WS-OD-OUT WS-OPTIONS
                               WS-HOUT WS-COMPCODE WS-REASON
           PERFORM UNTIL WS-COMPCODE NOT = 0
               CALL 'MQGET' USING WS-HCONN WS-HIN WS-MD WS-GMO
                                  WS-BUFLEN WS-REQUEST WS-DATALEN
                                  WS-COMPCODE WS-REASON
               IF WS-COMPCODE = 0
                   PERFORM 1000-REPLY
               END-IF
           END-PERFORM
           CALL 'MQCLOSE' USING WS-HCONN WS-HIN WS-OPTIONS
                                WS-COMPCODE WS-REASON
           CALL 'MQCLOSE' USING WS-HCONN WS-HOUT WS-OPTIONS
                                WS-COMPCODE WS-REASON
           DISPLAY 'MQLSN REPLIES ' WS-COUNT
           GOBACK.
       1000-REPLY.
           ADD 1 TO WS-COUNT
           MOVE RQ-CUST-ID TO RP-CUST-ID
           IF RQ-AMOUNT > 1000
               COMPUTE RP-FEE = RQ-AMOUNT * 0.02
               MOVE 'HI' TO RP-CODE
           ELSE
               MOVE 5 TO RP-FEE
               MOVE 'LO' TO RP-CODE
           END-IF
           CALL 'MQPUT' USING WS-HCONN WS-HOUT WS-MD WS-PMO
                              WS-BUFLEN WS-REPLY
                              WS-COMPCODE WS-REASON.
