       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSXALT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST ASSIGN TO CUSTF
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CK-ID
               ALTERNATE RECORD KEY IS CK-BR WITH DUPLICATES
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST.
       01  CUST-REC.
           05  CK-ID          PIC 9(4).
           05  CK-BR          PIC X(3).
           05  CK-NAME        PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-FS              PIC XX.
       01  WS-CNT             PIC 9(4) VALUE 0.
       01  WS-FOUND           PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CUST
           MOVE 1 TO CK-ID
           READ CUST
               INVALID KEY MOVE 'N' TO WS-FOUND
               NOT INVALID KEY MOVE 'Y' TO WS-FOUND
           END-READ
           MOVE "BR1" TO CK-BR
           READ CUST KEY IS CK-BR
               INVALID KEY MOVE 'N' TO WS-FOUND
               NOT INVALID KEY MOVE 'Y' TO WS-FOUND
           END-READ
           PERFORM UNTIL WS-FS NOT = "00"
               READ CUST NEXT
                   AT END CONTINUE
                   NOT AT END ADD 1 TO WS-CNT
               END-READ
           END-PERFORM
           CLOSE CUST
           GOBACK.
