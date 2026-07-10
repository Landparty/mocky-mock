"""Unit tests for the DATA DIVISION EXEC SQL transform."""

from mockymock.splicer.sqlca import transform_data_division_exec

BASE = [
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. SQLPGM.",
    "DATA DIVISION.",
    "WORKING-STORAGE SECTION.",
    "    EXEC SQL INCLUDE SQLCA END-EXEC.",
    "01  WS-CUST-ID PIC 9(5).",
    "PROCEDURE DIVISION.",
    "DO-SQL.",
    "    EXEC SQL",
    "        UPDATE ORDERS SET STATUS = 'Y'",
    "    END-EXEC.",
]


def test_include_sqlca_is_replaced_with_generated_fields():
    lines, reasons = transform_data_division_exec(BASE)
    assert reasons == []
    joined = "\n".join(lines)
    assert "01  SQLCA." in joined
    assert "05  SQLCODE" in joined
    assert "05  SQLSTATE" in joined
    assert "EXEC SQL INCLUDE SQLCA END-EXEC." not in joined


def test_procedure_division_exec_sql_is_untouched():
    lines, _ = transform_data_division_exec(BASE)
    assert "    EXEC SQL" in lines
    assert "        UPDATE ORDERS SET STATUS = 'Y'" in lines


def test_multiline_include_sqlca_is_replaced():
    src = (
        BASE[:4] + ["    EXEC SQL", "        INCLUDE SQLCA", "    END-EXEC."] + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    assert "01  SQLCA." in "\n".join(lines)


def test_declare_section_markers_are_commented_out():
    src = (
        BASE[:5]
        + [
            "    EXEC SQL BEGIN DECLARE SECTION END-EXEC.",
            "01  WS-HOST-VAR PIC X(10).",
            "    EXEC SQL END DECLARE SECTION END-EXEC.",
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    joined = "\n".join(lines)
    assert "*> " in joined
    assert "01  WS-HOST-VAR PIC X(10)." in lines  # host var stays live
    live = [
        ln
        for ln in lines
        if "DECLARE SECTION" in ln and not ln.strip().startswith("*>")
    ]
    assert live == []


def test_declare_table_is_commented_out():
    src = (
        BASE[:5]
        + [
            "    EXEC SQL DECLARE ORDERS TABLE",
            "        (ID INTEGER NOT NULL)",
            "    END-EXEC.",
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    live = [
        ln
        for ln in lines
        if "DECLARE ORDERS TABLE" in ln and not ln.strip().startswith("*>")
    ]
    assert live == []


def test_declare_cursor_is_commented_out():
    src = (
        BASE[:5]
        + [
            "    EXEC SQL DECLARE ACCT_CURSOR CURSOR FOR",
            "        SELECT ACCT_ID, BALANCE FROM ACCOUNTS",
            "        WHERE STATUS = 'A'",
            "    END-EXEC.",
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    live = [
        ln
        for ln in lines
        if "DECLARE ACCT_CURSOR CURSOR" in ln and not ln.strip().startswith("*>")
    ]
    assert live == []


def test_declare_cursor_for_update_is_commented_out():
    src = (
        BASE[:5]
        + [
            "    EXEC SQL DECLARE ACCT_CURSOR CURSOR FOR",
            "        SELECT ACCT_ID, BALANCE FROM ACCOUNTS",
            "        WHERE STATUS = 'A'",
            "        FOR UPDATE OF BALANCE",
            "    END-EXEC.",
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    live = [
        ln
        for ln in lines
        if "DECLARE ACCT_CURSOR CURSOR" in ln and not ln.strip().startswith("*>")
    ]
    assert live == []


def test_include_other_member_without_copybook_path_refuses_unresolved():
    src = BASE[:5] + ["    EXEC SQL INCLUDE ORDHOST END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(src)
    assert len(reasons) == 1
    assert reasons[0].code == "UNRESOLVED_COPYBOOK"
    assert "ORDHOST" in reasons[0].message


def test_unrecognized_data_division_exec_refuses():
    src = BASE[:5] + ["    EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC."] + BASE[5:]
    _, reasons = transform_data_division_exec(src)
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_DATA_DIVISION_EXEC"


def test_program_without_data_division_exec_is_unchanged():
    src = [ln for ln in BASE if "INCLUDE SQLCA" not in ln]
    lines, reasons = transform_data_division_exec(src)
    assert lines == src
    assert reasons == []


# --- literal-text false positive and shared-line guards (audit 2.6) ----------


def test_exec_sql_inside_value_literal_is_not_a_block():
    """`VALUE "EXEC SQL ERROR"` used to start a bogus block scan that could
    comment out every live data item up to the next real END-EXEC."""
    src = (
        BASE[:5]
        + [
            '01  WS-MSG PIC X(20) VALUE "EXEC SQL ERROR".',
            "01  WS-LIVE PIC X(5).",
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    assert '01  WS-MSG PIC X(20) VALUE "EXEC SQL ERROR".' in lines
    assert "01  WS-LIVE PIC X(5)." in lines


def test_end_exec_inside_value_literal_does_not_terminate_a_block():
    """A literal containing END-EXEC must not end a real block early; the
    real END-EXEC further down still terminates it."""
    src = (
        BASE[:4]
        + [
            "    EXEC SQL",
            "        INCLUDE SQLCA",
            "    END-EXEC.",
            '01  WS-NOTE PIC X(10) VALUE "END-EXEC".',
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    assert '01  WS-NOTE PIC X(10) VALUE "END-EXEC".' in lines
    assert "01  SQLCA." in "\n".join(lines)


def test_trailing_content_on_end_exec_line_refuses():
    """Whole-line replacement would delete a data item sharing the
    END-EXEC. line -- refuse instead."""
    src = (
        BASE[:4]
        + [
            "    EXEC SQL INCLUDE SQLCA END-EXEC. 01  WS-GLUED PIC X.",
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_DATA_DIVISION_EXEC"
    assert "trailing content" in reasons[0].message
    assert "    EXEC SQL INCLUDE SQLCA END-EXEC. 01  WS-GLUED PIC X." in lines


def test_leading_content_before_exec_sql_refuses():
    src = (
        BASE[:4]
        + [
            "01  WS-BEFORE PIC X. EXEC SQL INCLUDE SQLCA END-EXEC.",
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_DATA_DIVISION_EXEC"
    assert "shares its first line" in reasons[0].message


def test_commented_out_exec_sql_is_not_a_block():
    """A `*>` inline comment containing `EXEC SQL ... END-EXEC` (a
    commented-out declaration, or a stray line starting right after the
    indicator area) must not start a bogus block scan -- normalize_fixed_
    format only drops column-7 `*`/`/` full-line comments, so `*>` inline
    comments still reach this scanner as ordinary text unless it accounts
    for them itself."""
    src = (
        BASE[:4]
        + [
            "*> EXEC SQL INCLUDE SQLCA END-EXEC -- disabled for now",
            "01  WS-LIVE PIC X(5).",
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    assert "*> EXEC SQL INCLUDE SQLCA END-EXEC -- disabled for now" in lines
    assert "01  WS-LIVE PIC X(5)." in lines
    assert "01  SQLCA." not in "\n".join(lines)


def test_commented_out_end_exec_does_not_terminate_a_real_block():
    """A `*> END-EXEC` inline comment inside a real block must not
    terminate the scan early -- the real END-EXEC further down still
    closes it."""
    src = (
        BASE[:4]
        + [
            "    EXEC SQL",
            "        INCLUDE SQLCA",
            "*> reminder: END-EXEC below closes this block",
            "    END-EXEC.",
        ]
        + BASE[5:]
    )
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    assert "01  SQLCA." in "\n".join(lines)


# --- EXEC SQL INCLUDE <member> resolution via --copybook-path -----------------


def test_include_other_member_resolves_with_copybook_path(tmp_path):
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    (copybook_dir / "ORDHOST.CPY").write_text(
        "       01  ORD-HOST.\n           05  ORD-AMOUNT PIC 9(5)V99.\n"
    )
    src = BASE[:5] + ["    EXEC SQL INCLUDE ORDHOST END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(
        src, copybook_paths=[str(copybook_dir)]
    )
    assert reasons == []
    joined = "\n".join(lines)
    assert "ORD-AMOUNT PIC 9(5)V99" in joined
    assert "EXEC SQL INCLUDE ORDHOST END-EXEC." not in joined


def test_include_member_with_embedded_declare_table_is_commented_out(tmp_path):
    """A DCLGEN-style copybook embeds its own EXEC SQL DECLARE ... TABLE
    stanza right before the host-variable record -- the re-scan after
    splicing must catch and comment it out via the same DECLARE-TABLE
    branch that already handles a directly-authored one, with no new
    recursion code."""
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    (copybook_dir / "CUSTREC.CPY").write_text(
        "           EXEC SQL DECLARE CUSTREC TABLE\n"
        "           ( CUST_ID     INTEGER NOT NULL,\n"
        "             CUST_NAME   CHAR(30) )\n"
        "           END-EXEC.\n"
        "       01  CUSTREC.\n"
        "           05  CUST-ID         PIC S9(9) COMP-5.\n"
        "           05  CUST-NAME       PIC X(30).\n"
    )
    src = BASE[:5] + ["    EXEC SQL INCLUDE CUSTREC END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(
        src, copybook_paths=[str(copybook_dir)]
    )
    assert reasons == []
    joined = "\n".join(lines)
    assert "01  CUSTREC." in joined
    assert "05  CUST-ID" in joined
    live_declare = [
        ln
        for ln in lines
        if "DECLARE CUSTREC TABLE" in ln and not ln.strip().startswith("*>")
    ]
    assert live_declare == []


def test_nested_include_inside_resolved_member_refuses(tmp_path):
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    (copybook_dir / "OUTER.CPY").write_text("       EXEC SQL INCLUDE INNER END-EXEC.\n")
    (copybook_dir / "INNER.CPY").write_text("       01  INNER-FIELD PIC X(5).\n")
    src = BASE[:5] + ["    EXEC SQL INCLUDE OUTER END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(
        src, copybook_paths=[str(copybook_dir)]
    )
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_DATA_DIVISION_EXEC"
    assert "nested" in reasons[0].message
    assert "INNER" in reasons[0].message


def test_include_missing_member_with_copybook_path_refuses_unresolved(tmp_path):
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    src = BASE[:5] + ["    EXEC SQL INCLUDE NOPE END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(
        src, copybook_paths=[str(copybook_dir)]
    )
    assert len(reasons) == 1
    assert reasons[0].code == "UNRESOLVED_COPYBOOK"
    assert "NOPE" in reasons[0].message


def test_sqlca_include_still_uses_generated_fields_not_resolution(tmp_path):
    """INCLUDE SQLCA must keep using the hardcoded SQLCA_FIELDS path even
    when a --copybook-path happens to be given -- it must never go through
    member resolution (there is no SQLCA.CPY file to find)."""
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    lines, reasons = transform_data_division_exec(
        BASE, copybook_paths=[str(copybook_dir)]
    )
    assert reasons == []
    assert "01  SQLCA." in "\n".join(lines)
