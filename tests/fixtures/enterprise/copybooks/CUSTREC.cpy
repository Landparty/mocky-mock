      *  Customer record layout -- shared across the shop
           05  :PFX:-CUST-ID       PIC X(8).
           05  :PFX:-CUST-NAME     PIC X(30).
           05  :PFX:-BALANCE       PIC S9(9)V99 COMP-3.
           05  :PFX:-STATUS        PIC X.
               88  :PFX:-ACTIVE    VALUE 'A'.
               88  :PFX:-CLOSED    VALUE 'C'.
           05  :PFX:-ADDRESS.
               10  :PFX:-STREET    PIC X(30).
               10  :PFX:-CITY      PIC X(20).
               10  :PFX:-POSTCODE  PIC X(10).
