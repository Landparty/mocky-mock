       IDENTIFICATION DIVISION.
       PROGRAM-ID. LESERV.
      *================================================================*
      * Program type: Language Environment services program.           *
      * CEE date/time services, CEEMOUT message output, CEEGTST heap   *
      * storage with a POINTER, a user condition handler registered    *
      * with CEEHDLR through a PROCEDURE-POINTER, CEE3ABD, and the     *
      * intrinsic FUNCTIONs that replace many CEE calls.               *
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  FEEDBACK-CODE.
           05  FB-SEVERITY         PIC S9(4) COMP.
           05  FB-MSG-NO           PIC S9(4) COMP.
           05  FB-CASE-SEV-CTL     PIC X.
           05  FB-FACILITY-ID      PIC X(3).
           05  FB-I-S-INFO         PIC S9(9) COMP.
       01  CHAR-DATE.
           05  CD-LENGTH           PIC S9(4) COMP VALUE 10.
           05  CD-STRING           PIC X(10) VALUE '2026-09-15'.
       01  PICTURE-STRING.
           05  PS-LENGTH           PIC S9(4) COMP VALUE 10.
           05  PS-STRING           PIC X(10) VALUE 'YYYY-MM-DD'.
       01  OUT-PICTURE.
           05  OP-LENGTH           PIC S9(4) COMP VALUE 20.
           05  OP-STRING           PIC X(20) VALUE 'Wwwwwwwwwz, ZD Mmm'.
       01  LILIAN-DATE             PIC S9(9) COMP.
       01  FORMATTED-DATE          PIC X(20).
       01  MESSAGE-STRING.
           05  MS-LENGTH           PIC S9(4) COMP VALUE 40.
           05  MS-STRING           PIC X(40).
       01  DESTINATION             PIC S9(9) COMP VALUE 2.
       01  HEAP-ID                 PIC S9(9) COMP VALUE 0.
       01  HEAP-SIZE               PIC S9(9) COMP VALUE 4096.
       01  HEAP-ADDRESS            USAGE POINTER.
       01  HANDLER-ROUTINE         USAGE PROCEDURE-POINTER.
       01  HANDLER-TOKEN           PIC S9(9) COMP VALUE 0.
       01  ABEND-CODE              PIC S9(9) COMP VALUE 4093.
       01  ABEND-TIMING            PIC S9(9) COMP VALUE 1.
       01  WS-SECONDS              PIC S9(9) COMP.
       01  WS-CURRENT-DATE.
           05  WS-CD-YYYYMMDD      PIC 9(8).
           05  WS-CD-HHMMSS        PIC 9(6).
           05  FILLER              PIC X(7).
       01  WS-INTEGER-DATE         PIC 9(7).
       01  WS-UPPER-NAME           PIC X(20).
       LINKAGE SECTION.
       01  HEAP-BUFFER             PIC X(4096).
       PROCEDURE DIVISION.
       0000-MAIN.
           SET HANDLER-ROUTINE TO ENTRY 'LESERVHD'
           CALL 'CEEHDLR' USING HANDLER-ROUTINE HANDLER-TOKEN
                                FEEDBACK-CODE
           PERFORM 1000-DATE-SERVICES
           PERFORM 2000-HEAP-SERVICES
           PERFORM 3000-INTRINSICS
           CALL 'CEEHDLU' USING HANDLER-ROUTINE FEEDBACK-CODE
           GOBACK.
       1000-DATE-SERVICES.
           CALL 'CEEDAYS' USING CHAR-DATE PICTURE-STRING LILIAN-DATE
                                FEEDBACK-CODE
           IF FB-SEVERITY NOT = 0
               MOVE 'CEEDAYS FAILED' TO MS-STRING
               CALL 'CEEMOUT' USING MESSAGE-STRING DESTINATION
                                    FEEDBACK-CODE
               CALL 'CEE3ABD' USING ABEND-CODE ABEND-TIMING
           END-IF
           CALL 'CEEDATE' USING LILIAN-DATE OUT-PICTURE FORMATTED-DATE
                                FEEDBACK-CODE
           MOVE FORMATTED-DATE TO MS-STRING
           CALL 'CEEMOUT' USING MESSAGE-STRING DESTINATION
                                FEEDBACK-CODE
           CALL 'CEEGMT' USING LILIAN-DATE WS-SECONDS FEEDBACK-CODE.
       2000-HEAP-SERVICES.
           CALL 'CEEGTST' USING HEAP-ID HEAP-SIZE HEAP-ADDRESS
                                FEEDBACK-CODE
           IF FB-SEVERITY = 0
               SET ADDRESS OF HEAP-BUFFER TO HEAP-ADDRESS
               MOVE ALL '-' TO HEAP-BUFFER
               CALL 'CEEFRST' USING HEAP-ADDRESS FEEDBACK-CODE
           END-IF.
       3000-INTRINSICS.
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE
           COMPUTE WS-INTEGER-DATE =
               FUNCTION INTEGER-OF-DATE(WS-CD-YYYYMMDD)
           MOVE FUNCTION UPPER-CASE(FORMATTED-DATE) TO WS-UPPER-NAME
           IF FUNCTION TEST-DATE-YYYYMMDD(WS-CD-YYYYMMDD) NOT = 0
               DISPLAY 'BAD DATE ' WS-CD-YYYYMMDD
           END-IF
           DISPLAY FUNCTION TRIM(WS-UPPER-NAME)
                   ' LEN=' FUNCTION LENGTH(WS-UPPER-NAME)
                   ' DOW=' FUNCTION MOD(WS-INTEGER-DATE 7).
