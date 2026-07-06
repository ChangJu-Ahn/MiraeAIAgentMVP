"""Unit tests for _table_to_markdown function."""

from ingest.parser import _table_to_markdown


def test_normal_2x2_table():
    """Test that a normal 2x2 table renders correctly with header and divider."""
    table = {
        "rowCount": 2,
        "columnCount": 2,
        "cells": [
            {"rowIndex": 0, "columnIndex": 0, "content": "Header1"},
            {"rowIndex": 0, "columnIndex": 1, "content": "Header2"},
            {"rowIndex": 1, "columnIndex": 0, "content": "Row1Col1"},
            {"rowIndex": 1, "columnIndex": 1, "content": "Row1Col2"},
        ],
    }
    result = _table_to_markdown(table)
    lines = result.split("\n")

    assert len(lines) == 3
    assert "Header1" in lines[0] and "Header2" in lines[0]
    assert lines[1] == "|---|---|"
    assert "Row1Col1" in lines[2] and "Row1Col2" in lines[2]


def test_pipe_escaping():
    """Test that pipes in cell content are escaped."""
    table = {
        "rowCount": 2,
        "columnCount": 1,
        "cells": [
            {"rowIndex": 0, "columnIndex": 0, "content": "Header"},
            {"rowIndex": 1, "columnIndex": 0, "content": "A|B"},
        ],
    }
    result = _table_to_markdown(table)

    assert "A\\|B" in result
    assert "A|B" not in result.replace("A\\|B", "")


def test_empty_table():
    """Test that an empty table returns an empty string."""
    table = {
        "rowCount": 0,
        "columnCount": 0,
        "cells": [],
    }
    result = _table_to_markdown(table)

    assert result == ""


def test_newline_replacement():
    """Test that newlines in cell content are replaced with spaces."""
    table = {
        "rowCount": 2,
        "columnCount": 1,
        "cells": [
            {"rowIndex": 0, "columnIndex": 0, "content": "Header"},
            {"rowIndex": 1, "columnIndex": 0, "content": "Line1\nLine2"},
        ],
    }
    result = _table_to_markdown(table)

    assert "Line1 Line2" in result
    assert "\n" not in result.split("|\n")[1]  # no newline within markdown cells


def test_pipe_and_newline_combined():
    """Test that both pipes and newlines are handled correctly."""
    table = {
        "rowCount": 2,
        "columnCount": 1,
        "cells": [
            {"rowIndex": 0, "columnIndex": 0, "content": "Header"},
            {"rowIndex": 1, "columnIndex": 0, "content": "A|B\nC|D"},
        ],
    }
    result = _table_to_markdown(table)

    assert "A\\|B C\\|D" in result
