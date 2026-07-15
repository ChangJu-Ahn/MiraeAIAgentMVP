"""Tests for ingest/structured_indexer.py — TDD RED → GREEN."""
from __future__ import annotations

import base64
import re
from unittest.mock import MagicMock, call, patch

import pytest

from ingest.catalog import FundCatalogEntry
from ingest.facts import EvaluationFact
from ingest.structured_indexer import (
    build_catalog_index,
    build_facts_index,
    ensure_structured_indexes,
    replace_catalog,
    replace_facts,
)


# ── Schema tests ──────────────────────────────────────────────────────────────


def test_catalog_index_has_key_field():
    idx = build_catalog_index("cat-idx")
    assert idx.name == "cat-idx"
    key_field = next(f for f in idx.fields if f.name == "id")
    assert key_field.key is True


def test_catalog_fund_id_filterable_and_facetable():
    idx = build_catalog_index("cat-idx")
    fld = next(f for f in idx.fields if f.name == "fund_id")
    assert fld.filterable and fld.facetable


def test_catalog_toc_order_filterable_and_sortable():
    idx = build_catalog_index("cat-idx")
    fld = next(f for f in idx.fields if f.name == "toc_order")
    assert fld.filterable and fld.sortable


def test_catalog_year_filterable():
    idx = build_catalog_index("cat-idx")
    fld = next(f for f in idx.fields if f.name == "year")
    assert fld.filterable


def test_catalog_ministry_filterable_and_facetable():
    idx = build_catalog_index("cat-idx")
    fld = next(f for f in idx.fields if f.name == "ministry")
    assert fld.filterable and fld.facetable


def test_catalog_aliases_is_collection():
    from azure.search.documents.indexes.models import SearchFieldDataType

    idx = build_catalog_index("cat-idx")
    fld = next(f for f in idx.fields if f.name == "aliases")
    assert fld.type == SearchFieldDataType.Collection(SearchFieldDataType.String)


def test_catalog_doc_id_filterable():
    idx = build_catalog_index("cat-idx")
    fld = next(f for f in idx.fields if f.name == "doc_id")
    assert fld.filterable


def test_catalog_start_page_printed_sortable():
    idx = build_catalog_index("cat-idx")
    fld = next(f for f in idx.fields if f.name == "start_page_printed")
    assert fld.filterable and fld.sortable


def test_facts_index_has_key_field():
    idx = build_facts_index("facts-idx")
    assert idx.name == "facts-idx"
    key_field = next(f for f in idx.fields if f.name == "id")
    assert key_field.key is True


def test_fact_score_is_filterable_and_sortable():
    idx = build_facts_index("facts-idx")
    score = next(f for f in idx.fields if f.name == "score")
    assert score.filterable and score.sortable


def test_fact_max_score_is_filterable_and_sortable():
    idx = build_facts_index("facts-idx")
    fld = next(f for f in idx.fields if f.name == "max_score")
    assert fld.filterable and fld.sortable


def test_fact_score_is_double():
    from azure.search.documents.indexes.models import SearchFieldDataType

    idx = build_facts_index("facts-idx")
    score = next(f for f in idx.fields if f.name == "score")
    assert score.type == SearchFieldDataType.Double


def test_fact_grade_rank_filterable_and_sortable():
    idx = build_facts_index("facts-idx")
    fld = next(f for f in idx.fields if f.name == "grade_rank")
    assert fld.filterable and fld.sortable


def test_fact_fund_id_filterable_and_facetable():
    idx = build_facts_index("facts-idx")
    fld = next(f for f in idx.fields if f.name == "fund_id")
    assert fld.filterable and fld.facetable


def test_fact_year_filterable():
    idx = build_facts_index("facts-idx")
    fld = next(f for f in idx.fields if f.name == "year")
    assert fld.filterable


def test_fact_ministry_filterable_and_facetable():
    idx = build_facts_index("facts-idx")
    fld = next(f for f in idx.fields if f.name == "ministry")
    assert fld.filterable and fld.facetable


def test_fact_doc_id_filterable():
    idx = build_facts_index("facts-idx")
    fld = next(f for f in idx.fields if f.name == "doc_id")
    assert fld.filterable


def test_fact_source_fields_present():
    idx = build_facts_index("facts-idx")
    names = {f.name for f in idx.fields}
    assert {"source_chunk_id", "source_page_physical", "source_section_path", "source_text"} <= names


def test_fact_analytics_fields_present_and_queryable():
    idx = build_facts_index("facts-idx")
    fields = {f.name: f for f in idx.fields}
    assert {
        "metric_value", "unit", "pre_grade", "final_grade", "adjustment",
        "source_scope", "population_scope",
    } <= fields.keys()
    for name in ("metric_value", "adjustment"):
        assert fields[name].filterable and fields[name].sortable
    for name in ("unit", "pre_grade", "final_grade", "source_scope", "population_scope"):
        assert fields[name].filterable


# ── Settings tests ────────────────────────────────────────────────────────────


def test_settings_catalog_index_default():
    from config.settings import Settings

    s = Settings(_env_file=None)
    assert s.search_index_catalog == "fund-catalog-index"


def test_settings_facts_index_default():
    from config.settings import Settings

    s = Settings(_env_file=None)
    assert s.search_index_facts == "evaluation-facts-index"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _catalog_entry(toc_order: int = 1, doc_id: str = "doc1") -> FundCatalogEntry:
    return FundCatalogEntry(
        id=f"{doc_id}/{toc_order:03d}",
        fund_id="test_fund",
        year=2025,
        doc_id=doc_id,
        toc_order=toc_order,
        canonical_name="테스트기금",
        aliases=[],
        ministry="기획재정부",
        fund_scale=None,
        start_page_printed=10,
        end_page_printed=20,
        start_page_physical=None,
        end_page_physical=None,
        source_page_physical=5,
    )


def _fact(fact_id: str = "fact1", doc_id: str = "doc1") -> EvaluationFact:
    return EvaluationFact(
        id=fact_id,
        fund_id="test_fund",
        fund_name="테스트기금",
        doc_id=doc_id,
        year=2025,
        ministry="기획재정부",
        fact_type="score",
        metric_code="asset_management_performance",
        metric_name="자산운용 성과",
        score=80.0,
        max_score=100.0,
        grade=None,
        grade_rank=None,
        source_chunk_id="chunk1",
        source_page_physical=12,
        source_section_path="Ⅲ.1",
        source_text="some text",
    )


def _search_key(logical_id: str) -> str:
    token = base64.urlsafe_b64encode(logical_id.encode("utf-8")).decode("ascii")
    return f"b64_{token}"


# ── Validation tests ──────────────────────────────────────────────────────────


def test_replace_catalog_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        replace_catalog("doc1", [], _make_fake_search_client())


def test_replace_catalog_raises_on_wrong_doc_id():
    entry = _catalog_entry(doc_id="other_doc")
    with pytest.raises(ValueError, match="doc_id"):
        replace_catalog("doc1", [entry], _make_fake_search_client())


def test_replace_catalog_raises_on_duplicate_ids():
    e1 = _catalog_entry(toc_order=1)
    e2 = _catalog_entry(toc_order=1)  # same id
    with pytest.raises(ValueError, match="duplicate"):
        replace_catalog("doc1", [e1, e2], _make_fake_search_client())


def test_replace_catalog_raises_if_toc_order_not_starting_at_1():
    entry = _catalog_entry(toc_order=2)  # should start at 1
    with pytest.raises(ValueError, match="toc_order"):
        replace_catalog("doc1", [entry], _make_fake_search_client())


def test_replace_catalog_raises_if_toc_order_not_contiguous():
    e1 = _catalog_entry(toc_order=1)
    e2 = _catalog_entry(toc_order=3)  # gap
    e2.id = "doc1/003"
    with pytest.raises(ValueError, match="toc_order"):
        replace_catalog("doc1", [e1, e2], _make_fake_search_client())


def test_replace_facts_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        replace_facts("doc1", [], _make_fake_search_client())


def test_replace_facts_raises_on_duplicate_ids():
    f1 = _fact(fact_id="x")
    f2 = _fact(fact_id="x")
    with pytest.raises(ValueError, match="duplicate"):
        replace_facts("doc1", [f1, f2], _make_fake_search_client())


def test_replace_facts_raises_if_missing_provenance():
    f = EvaluationFact(
        id="fact1",
        fund_id="test_fund",
        fund_name="테스트기금",
        doc_id="doc1",
        year=2025,
        ministry="기획재정부",
        fact_type="score",
        metric_code="asset_management_performance",
        metric_name="자산운용 성과",
        source_chunk_id="",  # empty provenance
        source_page_physical=12,
        source_section_path="Ⅲ.1",
        source_text="some text",
    )
    with pytest.raises(ValueError, match="provenance"):
        replace_facts("doc1", [f], _make_fake_search_client())


def test_replace_catalog_uploads_search_safe_document_key():
    client = _make_fake_search_client()
    entry = _catalog_entry()

    replace_catalog("doc1", [entry], client)

    uploaded = client.upload_documents.call_args.kwargs["documents"]
    assert uploaded[0]["id"] == _search_key(entry.id)
    assert re.fullmatch(r"[A-Za-z0-9_=-]+", uploaded[0]["id"])


def test_replace_facts_uploads_search_safe_unicode_document_key():
    client = _make_fake_search_client()
    fact = _fact(fact_id="report-2025/국민연금기금/자산운용성과", doc_id="report-2025")

    replace_facts("report-2025", [fact], client)

    uploaded = client.upload_documents.call_args.kwargs["documents"]
    assert uploaded[0]["id"] == _search_key(fact.id)
    assert re.fullmatch(r"[A-Za-z0-9_=-]+", uploaded[0]["id"])


# ── Validation-before-delete ordering ────────────────────────────────────────


def test_replace_catalog_no_delete_on_validation_failure():
    """Validation failure must not trigger any delete or upload calls."""
    client = _make_fake_search_client()
    with pytest.raises(ValueError):
        replace_catalog("doc1", [], client)  # empty → validation error
    client.search.assert_not_called()
    client.delete_documents.assert_not_called()
    client.upload_documents.assert_not_called()


def test_replace_facts_no_delete_on_validation_failure():
    client = _make_fake_search_client()
    with pytest.raises(ValueError):
        replace_facts("doc1", [], client)
    client.search.assert_not_called()
    client.delete_documents.assert_not_called()
    client.upload_documents.assert_not_called()


# ── Happy-path delete + upload ────────────────────────────────────────────────


def test_replace_catalog_uploads_then_deletes_stale():
    """Upload new docs first, then delete only stale old keys."""
    current_key = _search_key("doc1/001")
    stale_key = _search_key("doc1/999")
    client = _make_fake_search_client(existing_ids=[current_key, stale_key])
    entries = [_catalog_entry(toc_order=1, doc_id="doc1")]  # id="doc1/001"

    replace_catalog("doc1", entries, client)

    assert client.search.called
    assert client.upload_documents.called
    assert client.delete_documents.called
    # Order: search → upload → delete (stale only)
    search_idx = _call_index(client, "search")
    upload_idx = _call_index(client, "upload_documents")
    delete_idx = _call_index(client, "delete_documents")
    assert search_idx < upload_idx < delete_idx


def test_replace_facts_uploads_then_deletes_stale():
    """Upload new docs first, then delete only stale old keys."""
    client = _make_fake_search_client(existing_ids=[_search_key("fact_old")])
    facts = [_fact(fact_id="fact1")]

    replace_facts("doc1", facts, client)

    assert client.search.called
    assert client.upload_documents.called
    assert client.delete_documents.called
    search_idx = _call_index(client, "search")
    upload_idx = _call_index(client, "upload_documents")
    delete_idx = _call_index(client, "delete_documents")
    assert search_idx < upload_idx < delete_idx


def test_replace_catalog_only_stale_keys_deleted():
    """Keys in both old and new sets must NOT be deleted."""
    current_key = _search_key("doc1/001")
    stale_key = _search_key("doc1/999")
    client = _make_fake_search_client(existing_ids=[current_key, stale_key])
    entries = [_catalog_entry(toc_order=1, doc_id="doc1")]  # id="doc1/001"
    replace_catalog("doc1", entries, client)

    deleted = client.delete_documents.call_args[1]["documents"]
    deleted_ids = {d["id"] for d in deleted}
    assert deleted_ids == {stale_key}


def test_replace_facts_only_stale_keys_deleted():
    """Keys in both old and new sets must NOT be deleted."""
    current_key = _search_key("fact1")
    stale_key = _search_key("fact_old")
    client = _make_fake_search_client(existing_ids=[current_key, stale_key])
    facts = [_fact(fact_id="fact1")]  # fact1 retained, fact_old stale
    replace_facts("doc1", facts, client)

    deleted = client.delete_documents.call_args[1]["documents"]
    deleted_ids = {d["id"] for d in deleted}
    assert deleted_ids == {stale_key}


def test_replace_catalog_no_delete_when_all_existing_are_new():
    """When every existing key is also in the new set, no delete call."""
    client = _make_fake_search_client(existing_ids=[_search_key("doc1/001")])
    entries = [_catalog_entry(toc_order=1, doc_id="doc1")]  # id="doc1/001"
    replace_catalog("doc1", entries, client)
    client.delete_documents.assert_not_called()


def test_replace_catalog_serializes_aliases():
    """aliases must be uploaded as a list of strings."""
    client = _make_fake_search_client()
    entry = _catalog_entry(toc_order=1, doc_id="doc1")
    entry.aliases = ["alias1", "alias2"]

    replace_catalog("doc1", [entry], client)

    uploaded = client.upload_documents.call_args[1]["documents"]
    doc = uploaded[0]
    assert doc["aliases"] == ["alias1", "alias2"]


def test_replace_catalog_skips_delete_when_no_existing():
    client = _make_fake_search_client(existing_ids=[])
    entries = [_catalog_entry(toc_order=1, doc_id="doc1")]
    replace_catalog("doc1", entries, client)
    client.delete_documents.assert_not_called()
    client.upload_documents.assert_called_once()


def test_replace_facts_partial_failure_raises():
    """A failed IndexingResult must raise RuntimeError."""
    client = _make_fake_search_client()
    bad_result = MagicMock()
    bad_result.succeeded = False
    bad_result.key = "fact1"
    bad_result.error_message = "boom"
    client.upload_documents.side_effect = None
    client.upload_documents.return_value = [bad_result]

    with pytest.raises(RuntimeError, match="fact1"):
        replace_facts("doc1", [_fact(fact_id="fact1")], client)


def test_replace_catalog_partial_delete_failure_raises():
    """Stale-key delete failure raises with key/error, new set already uploaded."""
    stale_key = _search_key("doc1/999")
    client = _make_fake_search_client(existing_ids=[stale_key])
    bad_result = MagicMock()
    bad_result.succeeded = False
    bad_result.key = stale_key
    bad_result.error_message = "del fail"
    client.delete_documents.side_effect = None
    client.delete_documents.return_value = [bad_result]

    with pytest.raises(RuntimeError, match=re.escape(stale_key)):
        replace_catalog("doc1", [_catalog_entry(toc_order=1, doc_id="doc1")], client)
    # Upload must have succeeded before delete was attempted
    assert client.upload_documents.called


def test_replace_catalog_no_delete_on_upload_result_failure():
    """When upload returns a failed IndexingResult with existing keys, zero deletes."""
    client = _make_fake_search_client(
        existing_ids=[_search_key("doc1/001"), _search_key("doc1/999")]
    )
    bad = MagicMock(
        succeeded=False, key=_search_key("doc1/001"), error_message="upload fail"
    )
    client.upload_documents.side_effect = None
    client.upload_documents.return_value = [bad]

    with pytest.raises(RuntimeError, match="upload fail"):
        replace_catalog("doc1", [_catalog_entry(toc_order=1, doc_id="doc1")], client)
    client.delete_documents.assert_not_called()


def test_replace_facts_no_delete_on_upload_result_failure():
    """When upload returns a failed IndexingResult with existing keys, zero deletes."""
    client = _make_fake_search_client(
        existing_ids=[_search_key("fact1"), _search_key("fact_old")]
    )
    bad = MagicMock(
        succeeded=False, key=_search_key("fact1"), error_message="upload fail"
    )
    client.upload_documents.side_effect = None
    client.upload_documents.return_value = [bad]

    with pytest.raises(RuntimeError, match="upload fail"):
        replace_facts("doc1", [_fact(fact_id="fact1")], client)
    client.delete_documents.assert_not_called()


def test_replace_catalog_no_delete_on_upload_transport_exception():
    """When upload raises a transport exception, zero delete calls."""
    client = _make_fake_search_client(existing_ids=[_search_key("doc1/001")])
    client.upload_documents.side_effect = Exception("network error")

    with pytest.raises(Exception, match="network error"):
        replace_catalog("doc1", [_catalog_entry(toc_order=1, doc_id="doc1")], client)
    client.delete_documents.assert_not_called()


def test_replace_facts_no_delete_on_upload_transport_exception():
    """When upload raises a transport exception, zero delete calls."""
    client = _make_fake_search_client(existing_ids=[_search_key("fact1")])
    client.upload_documents.side_effect = Exception("network error")

    with pytest.raises(Exception, match="network error"):
        replace_facts("doc1", [_fact(fact_id="fact1")], client)
    client.delete_documents.assert_not_called()


def test_replace_facts_wrong_doc_id_causes_no_calls():
    """Facts with doc_id different from supplied doc_id must fail validation."""
    f = _fact(fact_id="fact1", doc_id="doc1")
    client = _make_fake_search_client()
    with pytest.raises(ValueError, match="doc_id"):
        replace_facts("other_doc", [f], client)
    client.search.assert_not_called()
    client.delete_documents.assert_not_called()
    client.upload_documents.assert_not_called()


def test_replace_facts_serializes_doc_id_from_fact():
    """doc_id in uploaded documents comes from f.doc_id, not caller argument."""
    client = _make_fake_search_client()
    f = _fact(fact_id="fact1", doc_id="doc1")
    replace_facts("doc1", [f], client)
    uploaded = client.upload_documents.call_args[1]["documents"]
    assert uploaded[0]["doc_id"] == "doc1"


def test_replace_facts_serializes_analytics_fields():
    client = _make_fake_search_client()
    fact = _fact()
    fact.metric_value = 12.21
    fact.unit = "%"
    fact.pre_grade = "양호"
    fact.final_grade = "탁월"
    fact.adjustment = 1.0
    fact.source_scope = "annual_summary"
    fact.population_scope = "evaluated"

    replace_facts("doc1", [fact], client)

    uploaded = client.upload_documents.call_args.kwargs["documents"][0]
    assert uploaded["metric_value"] == pytest.approx(12.21)
    assert uploaded["unit"] == "%"
    assert uploaded["pre_grade"] == "양호"
    assert uploaded["final_grade"] == "탁월"
    assert uploaded["adjustment"] == pytest.approx(1.0)
    assert uploaded["source_scope"] == "annual_summary"
    assert uploaded["population_scope"] == "evaluated"


# ── ensure_structured_indexes ─────────────────────────────────────────────────


def test_ensure_structured_indexes_calls_create_or_update():
    mock_idx_client = MagicMock()
    mock_idx_client.create_or_update_index = MagicMock()

    with (
        patch("ingest.structured_indexer.SearchIndexClient", return_value=mock_idx_client),
        patch("ingest.structured_indexer.DefaultAzureCredential"),
        patch("ingest.structured_indexer.get_settings") as mock_gs,
    ):
        s = MagicMock()
        s.search_endpoint = "https://srch.example/"
        s.search_index_catalog = "fund-catalog-index"
        s.search_index_facts = "evaluation-facts-index"
        mock_gs.return_value = s
        ensure_structured_indexes()

    assert mock_idx_client.create_or_update_index.call_count == 2


# ── Helpers ───────────────────────────────────────────────────────────────────

_CALL_ORDER: list[str] = []


def _make_fake_search_client(existing_ids: list[str] | None = None) -> MagicMock:
    client = MagicMock()
    call_order: list[str] = []

    ids = existing_ids if existing_ids is not None else []
    search_results = [MagicMock(spec=["__getitem__"]) for _ in ids]
    for result, id_val in zip(search_results, ids):
        result.__getitem__ = lambda self, k, _id=id_val: _id if k == "id" else None

    def _search(*args, **kwargs):
        call_order.append("search")
        return iter(search_results)

    def _delete(*args, **kwargs):
        call_order.append("delete_documents")
        results = []
        for doc in kwargs.get("documents", args[0] if args else []):
            r = MagicMock()
            r.succeeded = True
            r.key = doc.get("id", "")
            r.error_message = None
            results.append(r)
        return results

    def _upload(*args, **kwargs):
        call_order.append("upload_documents")
        results = []
        for doc in kwargs.get("documents", args[0] if args else []):
            r = MagicMock()
            r.succeeded = True
            r.key = doc.get("id", "")
            r.error_message = None
            results.append(r)
        return results

    client.search = MagicMock(side_effect=_search)
    client.delete_documents = MagicMock(side_effect=_delete)
    client.upload_documents = MagicMock(side_effect=_upload)
    client._call_order = call_order
    return client


def _call_index(client: MagicMock, method: str) -> int:
    order = client._call_order
    return order.index(method)
