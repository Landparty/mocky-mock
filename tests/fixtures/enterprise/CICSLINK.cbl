       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSLINK.
      *================================================================*
      * Program type: CICS LINKed-to server program (translated form). *
      * DFHEIBLK and DFHCOMMAREA declared explicitly in LINKAGE and    *
      * passed on PROCEDURE DIVISION USING, as the CICS translator     *
      * leaves them; VSAM access through EXEC CICS READ/REWRITE with   *
      * UPDATE, HANDLE CONDITION, IGNORE CONDITION, and RETURN.        *
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP                 PIC S9(8) COMP.
       01  WS-CUST-RECORD.
           05  CUST-ID             PIC X(8).
           05  CUST-NAME           PIC X(30).
           05  CUST-BALANCE        PIC S9(9)V99 COMP-3.
           05  FILLER              PIC X(56).
       LINKAGE SECTION.
       01  DFHEIBLK.
           02  EIBTIME             PIC S9(7) COMP-3.
           02  EIBDATE             PIC S9(7) COMP-3.
           02  EIBTRNID            PIC X(4).
           02  EIBTASKN            PIC S9(7) COMP-3.
           02  EIBTRMID            PIC X(4).
           02  DFHEIGDI            PIC S9(4) COMP.
           02  EIBCPOSN            PIC S9(4) COMP.
           02  EIBCALEN            PIC S9(4) COMP.
           02  EIBAID              PIC X(1).
           02  EIBFN               PIC X(2).
           02  EIBRCODE            PIC X(6).
           02  EIBDS               PIC X(8).
           02  EIBREQID            PIC X(8).
           02  EIBRSRCE            PIC X(8).
           02  EIBSYNC             PIC X(1).
           02  EIBFREE             PIC X(1).
           02  EIBRECV             PIC X(1).
           02  EIBSEND             PIC X(1).
           02  EIBATT              PIC X(1).
           02  EIBEOC              PIC X(1).
           02  EIBFMH              PIC X(1).
           02  EIBCOMPL            PIC X(1).
           02  EIBSIG              PIC X(1).
           02  EIBCONF             PIC X(1).
           02  EIBERR              PIC X(1).
           02  EIBERRCD            PIC X(4).
           02  EIBSYNRB            PIC X(1).
           02  EIBNODAT            PIC X(1).
           02  EIBRESP             PIC S9(8) COMP.
           02  EIBRESP2            PIC S9(8) COMP.
           02  EIBRLDBK            PIC X(1).
       01  DFHCOMMAREA.
           05  CA-CUST-ID          PIC X(8).
           05  CA-ADJUSTMENT       PIC S9(7)V99 COMP-3.
           05  CA-RETURN-CODE      PIC S9(4) COMP.
       PROCEDURE DIVISION USING DFHEIBLK DFHCOMMAREA.
       0000-MAIN.
           IF EIBCALEN < LENGTH OF DFHCOMMAREA
               EXEC CICS ABEND ABCODE('LNK1') END-EXEC
           END-IF
           EXEC CICS HANDLE CONDITION
               NOTFND(9000-NOT-FOUND)
               ERROR(9100-ERROR)
           END-EXEC
           EXEC CICS IGNORE CONDITION LENGERR END-EXEC
           MOVE CA-CUST-ID TO CUST-ID
           EXEC CICS READ FILE('CUSTMST')
               INTO(WS-CUST-RECORD)
               RIDFLD(CUST-ID)
               UPDATE
           END-EXEC
           ADD CA-ADJUSTMENT TO CUST-BALANCE
           EXEC CICS REWRITE FILE('CUSTMST')
               FROM(WS-CUST-RECORD)
               RESP(WS-RESP)
           END-EXEC
           IF WS-RESP = DFHRESP(NORMAL)
               MOVE 0 TO CA-RETURN-CODE
           ELSE
               MOVE EIBRESP TO CA-RETURN-CODE
           END-IF
           EXEC CICS RETURN END-EXEC.
       9000-NOT-FOUND.
           MOVE 4 TO CA-RETURN-CODE
           EXEC CICS RETURN END-EXEC.
       9100-ERROR.
           MOVE EIBRESP TO CA-RETURN-CODE
           EXEC CICS SYNCPOINT ROLLBACK END-EXEC
           EXEC CICS RETURN END-EXEC.
