from ingest.indexer import build_index, _chunk_to_doc
from ingest.models import Chunk


def test_index_has_metadata_fields():
    names = {f.name for f in build_index("x").fields}
    assert {"year", "doc_type", "fund_name", "fund_scale"} <= names


def test_chunk_to_doc_writes_nonnull_metadata():
    c = Chunk(
        id="i", doc_id="d", content="c", chunk_type="table", section_path="s",
        page_physical=1, content_vector=[0.0], year=2022, doc_type="report",
        fund_name="국민연금기금", fund_scale=None,
    )
    doc = _chunk_to_doc(c)
    assert doc["year"] == 2022 and doc["doc_type"] == "report" and doc["fund_name"] == "국민연금기금"
    assert "fund_scale" not in doc  # None은 미적재
