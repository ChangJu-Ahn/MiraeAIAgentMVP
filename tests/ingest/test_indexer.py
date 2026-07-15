from ingest.indexer import build_index, _chunk_to_doc
from ingest.models import Chunk


def test_index_has_metadata_fields():
    names = {f.name for f in build_index("x").fields}
    assert {"year", "doc_type", "fund_name", "fund_scale"} <= names


def test_index_has_fund_id_and_ministry_fields():
    names = {f.name for f in build_index("x").fields}
    assert {"fund_id", "ministry"} <= names


def test_chunk_to_doc_writes_nonnull_metadata():
    c = Chunk(
        id="i", doc_id="d", content="c", chunk_type="table", section_path="s",
        page_physical=1, content_vector=[0.0], year=2022, doc_type="report",
        fund_name="국민연금기금", fund_scale=None,
    )
    doc = _chunk_to_doc(c)
    assert doc["year"] == 2022 and doc["doc_type"] == "report" and doc["fund_name"] == "국민연금기금"
    assert "fund_scale" not in doc  # None은 미적재


def test_chunk_to_doc_writes_fund_id_and_ministry():
    c = Chunk(
        id="i", doc_id="d", content="c", chunk_type="narrative", section_path="s",
        page_physical=1, content_vector=[0.0],
        fund_id="국민연금기금", ministry="보건복지부",
    )
    doc = _chunk_to_doc(c)
    assert doc["fund_id"] == "국민연금기금"
    assert doc["ministry"] == "보건복지부"


def test_chunk_to_doc_omits_null_fund_id():
    c = Chunk(
        id="i", doc_id="d", content="c", chunk_type="narrative", section_path="s",
        page_physical=1, content_vector=[0.0],
    )
    doc = _chunk_to_doc(c)
    assert "fund_id" not in doc
    assert "ministry" not in doc
