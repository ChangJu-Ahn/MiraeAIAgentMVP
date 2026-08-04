import re
from datetime import datetime, timezone

import chunking


def test_chunk_text_splits_by_size():
    assert chunking.chunk_text("abcdef", 2) == ["ab", "cd", "ef"]


def test_chunk_text_keeps_remainder():
    assert chunking.chunk_text("abcde", 2) == ["ab", "cd", "e"]


def test_chunk_text_shorter_than_size():
    assert chunking.chunk_text("abc", 10) == ["abc"]


def test_chunk_text_empty_or_whitespace():
    assert chunking.chunk_text("", 10) == []
    assert chunking.chunk_text("   \n\t ", 10) == []


def test_chunk_text_unicode_by_char():
    assert chunking.chunk_text("가나다라", 2) == ["가나", "다라"]


def test_chunk_text_rejects_nonpositive_size():
    import pytest

    with pytest.raises(ValueError):
        chunking.chunk_text("abc", 0)


def test_sanitize_key_only_safe_chars():
    out = chunking.sanitize_key("2025 보고서.pdf")
    assert re.fullmatch(r"[A-Za-z0-9_\-=]+", out)


def test_sanitize_key_empty_fallback():
    assert chunking.sanitize_key("") == "doc"


def test_build_documents_pages_and_indexes():
    pages = ["A" * 5, "B" * 3]
    docs = chunking.build_documents(
        "f.pdf", pages, chunk_size=2,
        uploaded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert len(docs) == 5
    assert [d["page"] for d in docs] == [1, 1, 1, 2, 2]
    assert [d["chunk_index"] for d in docs] == [0, 1, 2, 3, 4]
    assert docs[0]["id"] == "f_pdf-0"
    assert docs[0]["content"] == "AA"
    assert docs[0]["source_file"] == "f.pdf"
    assert docs[0]["uploaded_at"] == "2026-01-01T00:00:00+00:00"


def test_build_documents_skips_empty_pages():
    assert chunking.build_documents("f.pdf", ["", "   "], chunk_size=100) == []
