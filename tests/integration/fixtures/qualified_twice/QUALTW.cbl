       IDENTIFICATION DIVISION.
       PROGRAM-ID. QUALTW.
      * A record copybook COPYed twice, plus one name declared twice
      * with different PICTUREs: EXPECTs name them with OF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  IN-TXN.
           COPY TXNREC.
       01  OUT-TXN.
           COPY TXNREC.
       01  IN-TOTALS.
           05  RATE           PIC 9(3).
       01  OUT-TOTALS.
           05  RATE           PIC 9V99.
       PROCEDURE DIVISION.
       0000-MAIN.
           COMPUTE TXN-AMT OF OUT-TXN = TXN-AMT OF IN-TXN * 2
           COMPUTE TXN-QTY OF OUT-TXN = TXN-QTY OF IN-TXN + 1
           MOVE TXN-AMT OF OUT-TXN TO TXN-AMT-ED OF OUT-TXN
           COMPUTE RATE OF OUT-TOTALS = RATE OF IN-TOTALS / 100
           GOBACK.
