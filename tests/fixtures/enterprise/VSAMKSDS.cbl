       IDENTIFICATION DIVISION.
       PROGRAM-ID. VSAMKSDS.
      *================================================================*
      * Program type: VSAM batch maintenance.                          *
      * KSDS with an alternate index (dynamic access, START/READ NEXT, *
      * REWRITE, DELETE), an RRDS addressed by RELATIVE KEY, and an    *
      * ESDS written sequentially. FILE STATUS checked on every verb.  *
      *================================================================*
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-MASTER ASSIGN TO CUSTMST
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CM-CUST-ID
               ALTERNATE RECORD KEY IS CM-CUST-NAME WITH DUPLICATES
               FILE STATUS IS WS-CM-STATUS WS-CM-VSAM-CODE.
           SELECT RATE-TABLE ASSIGN TO RATETBL
               ORGANIZATION IS RELATIVE
               ACCESS MODE IS RANDOM
               RELATIVE KEY IS WS-RATE-RRN
               FILE STATUS IS WS-RT-STATUS.
           SELECT AUDIT-LOG ASSIGN TO AS-AUDITLOG
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-AL-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-MASTER.
       01  CUST-MASTER-REC.
           05  CM-CUST-ID          PIC X(8).
           05  CM-CUST-NAME        PIC X(30).
           05  CM-BALANCE          PIC S9(9)V99 COMP-3.
           05  CM-RATE-CODE        PIC 9(3).
           05  CM-STATUS           PIC X.
               88  CM-ACTIVE       VALUE 'A'.
               88  CM-CLOSED       VALUE 'C'.
           05  FILLER              PIC X(20).
       FD  RATE-TABLE.
       01  RATE-REC.
           05  RT-RATE             PIC 9V9(5).
           05  RT-DESC             PIC X(20).
       FD  AUDIT-LOG.
       01  AUDIT-REC.
           05  AL-CUST-ID          PIC X(8).
           05  AL-ACTION           PIC X(10).
           05  AL-OLD-BALANCE      PIC S9(9)V99 COMP-3.
           05  AL-NEW-BALANCE      PIC S9(9)V99 COMP-3.
       WORKING-STORAGE SECTION.
       01  WS-FILE-STATUS.
           05  WS-CM-STATUS        PIC XX.
               88  CM-OK           VALUE '00' '02'.
               88  CM-NOT-FOUND    VALUE '23'.
               88  CM-EOF          VALUE '10'.
               88  CM-DUP-KEY      VALUE '22'.
           05  WS-CM-VSAM-CODE.
               10  WS-CM-RETURN    PIC S9(2) COMP.
               10  WS-CM-FUNCTION  PIC S9(1) COMP.
               10  WS-CM-FEEDBACK  PIC S9(3) COMP.
           05  WS-RT-STATUS        PIC XX.
           05  WS-AL-STATUS        PIC XX.
       01  WS-RATE-RRN             PIC 9(4) COMP.
       01  WS-SEARCH-NAME          PIC X(30).
       01  WS-INTEREST             PIC S9(9)V99 COMP-3.
       01  WS-BROWSE-DONE          PIC X VALUE 'N'.
           88  BROWSE-DONE         VALUE 'Y'.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN I-O CUST-MASTER
                INPUT RATE-TABLE
                OUTPUT AUDIT-LOG
           IF NOT CM-OK
               DISPLAY 'CUSTMST OPEN ' WS-CM-STATUS ' RC=' WS-CM-RETURN
               MOVE 12 TO RETURN-CODE
               GOBACK
           END-IF
           PERFORM 1000-BROWSE-BY-NAME
           PERFORM 2000-APPLY-INTEREST
           PERFORM 3000-PURGE-CLOSED
           CLOSE CUST-MASTER RATE-TABLE AUDIT-LOG
           GOBACK.
       1000-BROWSE-BY-NAME.
           MOVE 'SMITH' TO WS-SEARCH-NAME
           MOVE WS-SEARCH-NAME TO CM-CUST-NAME
           START CUST-MASTER KEY IS NOT LESS THAN CM-CUST-NAME
               INVALID KEY SET BROWSE-DONE TO TRUE
           END-START
           PERFORM UNTIL BROWSE-DONE
               READ CUST-MASTER NEXT RECORD
                   AT END SET BROWSE-DONE TO TRUE
                   NOT AT END
                       IF CM-CUST-NAME(1:5) NOT = 'SMITH'
                           SET BROWSE-DONE TO TRUE
                       ELSE
                           DISPLAY CM-CUST-ID ' ' CM-CUST-NAME
                       END-IF
               END-READ
           END-PERFORM.
       2000-APPLY-INTEREST.
           MOVE 'N' TO WS-BROWSE-DONE
           MOVE LOW-VALUES TO CM-CUST-ID
           START CUST-MASTER KEY IS GREATER THAN CM-CUST-ID
               INVALID KEY SET BROWSE-DONE TO TRUE
           END-START
           PERFORM UNTIL BROWSE-DONE
               READ CUST-MASTER NEXT
                   AT END SET BROWSE-DONE TO TRUE
                   NOT AT END PERFORM 2100-POST-ONE
               END-READ
           END-PERFORM.
       2100-POST-ONE.
           IF CM-ACTIVE
               MOVE CM-RATE-CODE TO WS-RATE-RRN
               READ RATE-TABLE
                   INVALID KEY MOVE ZERO TO RT-RATE
               END-READ
               COMPUTE WS-INTEREST ROUNDED = CM-BALANCE * RT-RATE
               MOVE CM-CUST-ID TO AL-CUST-ID
               MOVE 'INTEREST' TO AL-ACTION
               MOVE CM-BALANCE TO AL-OLD-BALANCE
               ADD WS-INTEREST TO CM-BALANCE
               MOVE CM-BALANCE TO AL-NEW-BALANCE
               REWRITE CUST-MASTER-REC
                   INVALID KEY DISPLAY 'REWRITE FAILED ' WS-CM-STATUS
               END-REWRITE
               WRITE AUDIT-REC
           END-IF.
       3000-PURGE-CLOSED.
           MOVE 'CLOSED01' TO CM-CUST-ID
           READ CUST-MASTER KEY IS CM-CUST-ID
               INVALID KEY CONTINUE
               NOT INVALID KEY
                   IF CM-CLOSED
                       DELETE CUST-MASTER RECORD
                           INVALID KEY DISPLAY 'DELETE FAILED'
                       END-DELETE
                   END-IF
           END-READ.
