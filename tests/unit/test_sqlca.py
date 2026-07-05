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
    src = BASE[:4] + ["    EXEC SQL", "        INCLUDE SQLCA", "    END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    assert "01  SQLCA." in "\n".join(lines)


def test_declare_section_markers_are_commented_out():
    src = BASE[:5] + [
        "    EXEC SQL BEGIN DECLARE SECTION END-EXEC.",
        "01  WS-HOST-VAR PIC X(10).",
        "    EXEC SQL END DECLARE SECTION END-EXEC.",
    ] + BASE[5:]
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    joined = "\n".join(lines)
    assert "*> " in joined
    assert "01  WS-HOST-VAR PIC X(10)." in lines  # host var stays live
    live = [ln for ln in lines if "DECLARE SECTION" in ln and not ln.strip().startswith("*>")]
    assert live == []


def test_declare_table_is_commented_out():
    src = BASE[:5] + [
        "    EXEC SQL DECLARE ORDERS TABLE",
        "        (ID INTEGER NOT NULL)",
        "    END-EXEC.",
    ] + BASE[5:]
    lines, reasons = transform_data_division_exec(src)
    assert reasons == []
    live = [ln for ln in lines if "DECLARE ORDERS TABLE" in ln and not ln.strip().startswith("*>")]
    assert live == []


def test_include_other_member_refuses():
    src = BASE[:5] + ["    EXEC SQL INCLUDE ORDHOST END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(src)
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_DATA_DIVISION_EXEC"
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
