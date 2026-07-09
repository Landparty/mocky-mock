from mockymock.splicer.stub_writer import comment_and_replace, insert_lines_after

SOURCE_LINES = [
    "       FIRST-PARAGRAPH.",
    '           CALL "DISCRATE"',
    "               USING WS-AMOUNT",
    "                     WS-RATE.",
    "",
    "       SECOND-PARAGRAPH.",
    '           DISPLAY "DONE".',
]


def test_comments_out_the_full_span():
    result = comment_and_replace(SOURCE_LINES, start_line=2, end_line=4, replacement=[])
    assert result[1].lstrip().startswith("*>")
    assert result[2].lstrip().startswith("*>")
    assert result[3].lstrip().startswith("*>")
    assert "CALL" in result[1]
    assert "WS-RATE" in result[3]


def test_does_not_touch_lines_outside_the_span():
    result = comment_and_replace(SOURCE_LINES, start_line=2, end_line=4, replacement=[])
    assert result[0] == SOURCE_LINES[0]
    assert result[5] == SOURCE_LINES[5]
    assert result[6] == SOURCE_LINES[6]


def test_blank_lines_in_span_are_left_blank():
    result = comment_and_replace(SOURCE_LINES, start_line=2, end_line=5, replacement=[])
    assert result[4] == ""


def test_replacement_lines_inserted_immediately_after_span():
    result = comment_and_replace(
        SOURCE_LINES,
        start_line=2,
        end_line=4,
        replacement=["           ADD 1 TO UT-DISCRATE-TALLY"],
    )
    assert result[4] == "           ADD 1 TO UT-DISCRATE-TALLY"
    assert result[5] == ""
    assert result[6] == "       SECOND-PARAGRAPH."


def test_does_not_mutate_input_list():
    original = list(SOURCE_LINES)
    comment_and_replace(SOURCE_LINES, start_line=2, end_line=4, replacement=[])
    assert SOURCE_LINES == original


def test_insert_lines_after_leaves_original_lines_untouched():
    lines = ["AAA", "BBB", "CCC"]
    result = insert_lines_after(lines, 2, ["NEW1", "NEW2"])
    assert result == ["AAA", "BBB", "NEW1", "NEW2", "CCC"]
    assert lines == ["AAA", "BBB", "CCC"]  # original list not mutated


def test_insert_lines_after_at_end_of_file():
    lines = ["AAA", "BBB"]
    result = insert_lines_after(lines, 2, ["NEW"])
    assert result == ["AAA", "BBB", "NEW"]


def test_insert_lines_after_no_new_lines_is_a_no_op():
    lines = ["AAA", "BBB"]
    assert insert_lines_after(lines, 1, []) == ["AAA", "BBB"]
