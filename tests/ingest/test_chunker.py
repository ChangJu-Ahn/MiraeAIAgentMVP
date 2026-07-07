from ingest.chunker import chunk_document
from tests.ingest.fixtures import make_doc


def test_tables_are_single_chunks():
    chunks = chunk_document(make_doc())
    tables = [c for c in chunks if c.chunk_type == "table"]
    assert len(tables) == 1
    assert "종합등급" in tables[0].content
    assert "| 등급 | 내용 |" in tables[0].content


def test_section_path_built_from_headings():
    chunks = chunk_document(make_doc())
    narrative = [c for c in chunks if c.chunk_type == "narrative"]
    # 긴 문단은 "가. 평가의 특징" 섹션에 속한다
    long_chunks = [c for c in narrative if "가나다" in c.content]
    assert long_chunks
    assert long_chunks[0].section_path == "Ⅱ. 자산운용부문 평가결과 > 1. 평가 개요 > 가. 평가의 특징"


def test_long_section_is_split_with_overlap():
    chunks = chunk_document(make_doc(), max_chars=400, overlap_chars=60)
    long_chunks = [c for c in chunks if c.chunk_type == "narrative" and "가나다" in c.content]
    assert len(long_chunks) >= 2
    # 오버랩: 다음 청크 시작이 이전 청크 끝 일부를 포함
    assert long_chunks[0].content[-30:] in long_chunks[1].content


def test_printed_page_number_captured():
    chunks = chunk_document(make_doc())
    page1 = [c for c in chunks if c.page_physical == 1 and c.chunk_type == "narrative"]
    assert any(c.page_printed == 24 for c in page1)


def test_ids_unique_and_prefixed():
    chunks = chunk_document(make_doc())
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("d1-") for i in ids)


def test_table_section_path_reflects_document_position():
    """Tables must get section_path active at their offset position, not the final heading."""
    chunks = chunk_document(make_doc())
    tables = [c for c in chunks if c.chunk_type == "table"]
    assert len(tables) == 1
    # Table offset=500 is AFTER "가. 평가의 특징" (offset=200) but BEFORE "나. 평가결과 공개" (offset=600)
    # So section_path should end with "가. 평가의 특징", NOT "나. 평가결과 공개"
    expected = "Ⅱ. 자산운용부문 평가결과 > 1. 평가 개요 > 가. 평가의 특징"
    assert tables[0].section_path == expected, f"Expected '{expected}' but got '{tables[0].section_path}'"


def _tbl(md, page, caption=None, offset=0):
    from ingest.models import ParsedTable

    return ParsedTable(markdown=md, page=page, caption=caption, offset=offset)


_H = "| 등급 | 내용 |\n|---|---|\n"


def test_merge_continuation_tables_merges_repeated_header_no_caption():
    from ingest.chunker import merge_continuation_tables

    tables = [
        _tbl(_H + "| 탁월 | 높음 |", page=1, caption="종합등급", offset=0),
        _tbl(_H + "| 우수 | 중간 |", page=2, caption=None, offset=100),  # 다음 페이지, 헤더 반복, 캡션 없음
    ]
    merged = merge_continuation_tables(tables)
    assert len(merged) == 1
    assert merged[0].markdown.count("| 등급 | 내용 |") == 1  # 헤더는 한 번만
    assert "탁월" in merged[0].markdown and "우수" in merged[0].markdown


def test_merge_keeps_distinct_captioned_tables_separate():
    from ingest.chunker import merge_continuation_tables

    tables = [
        _tbl(_H + "| 탁월 | 높음 |", page=1, caption="참고 7", offset=0),
        _tbl(_H + "| 우수 | 중간 |", page=2, caption="참고 8", offset=100),  # 둘 다 캡션 → 별개
    ]
    assert len(merge_continuation_tables(tables)) == 2


def test_merge_skips_non_consecutive_pages():
    from ingest.chunker import merge_continuation_tables

    tables = [
        _tbl(_H + "| 탁월 | 높음 |", page=1, offset=0),
        _tbl(_H + "| 우수 | 중간 |", page=3, caption=None, offset=100),  # 페이지 안 이어짐
    ]
    assert len(merge_continuation_tables(tables)) == 2


def test_merge_skips_different_header():
    from ingest.chunker import merge_continuation_tables

    tables = [
        _tbl(_H + "| 탁월 | 높음 |", page=1, offset=0),
        _tbl("| 구분 | 값 |\n|---|---|\n| A | 1 |", page=2, caption=None, offset=100),
    ]
    assert len(merge_continuation_tables(tables)) == 2
