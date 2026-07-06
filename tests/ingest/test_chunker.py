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
