       IDENTIFICATION DIVISION.
       PROGRAM-ID. KEYEND.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO CUSTF
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CUST-ID
               FILE STATUS IS WS-FS.
           SELECT REL-FILE ASSIGN TO RELF
               ORGANIZATION IS RELATIVE
               ACCESS MODE IS RANDOM
               RELATIVE KEY IS WS-RRN
               FILE STATUS IS WS-FS2.
           SELECT NOST-FILE ASSIGN TO NOSTF
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS NOST-ID.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05 CUST-ID    PIC X(5).
           05 CUST-NAME  PIC X(10).
       FD  REL-FILE.
       01  REL-REC       PIC X(10).
       FD  NOST-FILE.
       01  NOST-REC.
           05 NOST-ID    PIC X(5).
           05 NOST-NAME  PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FS        PIC XX.
       01  WS-FS2       PIC XX.
       01  WS-RRN       PIC 9(4).
       01  WS-FOUND     PIC 9(4) VALUE 0.
       01  WS-MISSING   PIC 9(4) VALUE 0.
       01  WS-I         PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       KSDS-PARA.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3
               MOVE WS-I TO CUST-ID
               READ CUST-FILE
                   INVALID KEY
                       ADD 1 TO WS-MISSING
                   NOT INVALID KEY
                       ADD 1 TO WS-FOUND
               END-READ
           END-PERFORM.
       RRDS-PARA.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3
               MOVE WS-I TO WS-RRN
               READ REL-FILE
                   INVALID KEY
                       ADD 1 TO WS-MISSING
                   NOT INVALID KEY
                       ADD 1 TO WS-FOUND
               END-READ
           END-PERFORM.
       NOSTATUS-PARA.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3
               MOVE WS-I TO NOST-ID
               READ NOST-FILE
                   INVALID KEY
                       ADD 1 TO WS-MISSING
                   NOT INVALID KEY
                       ADD 1 TO WS-FOUND
               END-READ
           END-PERFORM.
