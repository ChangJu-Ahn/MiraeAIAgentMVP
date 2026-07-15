"""Non-vector Azure AI Search indexes for fund catalog and evaluation facts.

Provides:
- ``build_catalog_index`` / ``build_facts_index`` — schema builders
- ``ensure_structured_indexes`` — create-or-update both indexes
- ``replace_catalog`` / ``replace_facts`` — validated replacement upload
"""
from __future__ import annotations

import base64

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SimpleField,
)

from config.settings import get_settings
from ingest.catalog import FundCatalogEntry
from ingest.facts import EvaluationFact

_BATCH = 1000
_SEARCH_KEY_PREFIX = "b64_"


def encode_search_key(logical_id: str) -> str:
    """Encode a logical identifier as an Azure AI Search-safe document key."""
    token = base64.urlsafe_b64encode(logical_id.encode("utf-8")).decode("ascii")
    return f"{_SEARCH_KEY_PREFIX}{token}"


def decode_search_key(search_key: str) -> str:
    """Restore a logical identifier encoded by :func:`encode_search_key`."""
    if not search_key.startswith(_SEARCH_KEY_PREFIX):
        return search_key
    token = search_key.removeprefix(_SEARCH_KEY_PREFIX)
    return base64.urlsafe_b64decode(token).decode("utf-8")


# ── Schema builders ───────────────────────────────────────────────────────────


def build_catalog_index(name: str) -> SearchIndex:
    """Return a ``SearchIndex`` definition for the fund catalog."""
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="fund_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="year", type=SearchFieldDataType.Int32, filterable=True, facetable=True),
        SimpleField(name="toc_order", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
        SearchableField(name="canonical_name", type=SearchFieldDataType.String, filterable=True),
        SimpleField(
            name="aliases",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        SimpleField(name="ministry", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="fund_scale", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="start_page_printed", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
        SimpleField(name="end_page_printed", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
        SimpleField(name="start_page_physical", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(name="end_page_physical", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(name="source_page_physical", type=SearchFieldDataType.Int32, filterable=True),
    ]
    return SearchIndex(name=name, fields=fields)


def build_facts_index(name: str) -> SearchIndex:
    """Return a ``SearchIndex`` definition for evaluation facts."""
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="fund_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="fund_name", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="year", type=SearchFieldDataType.Int32, filterable=True, facetable=True),
        SimpleField(name="ministry", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="fact_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="metric_code", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SearchableField(name="metric_name", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="metric_value", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="unit", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="score", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="max_score", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="pre_grade", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="final_grade", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="grade", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="grade_rank", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
        SimpleField(name="adjustment", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="source_scope", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="population_scope", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="source_chunk_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="source_page_physical", type=SearchFieldDataType.Int32, filterable=True),
        SearchableField(name="source_section_path", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="source_text", type=SearchFieldDataType.String),
    ]
    return SearchIndex(name=name, fields=fields)


# ── Index management ──────────────────────────────────────────────────────────


def ensure_structured_indexes() -> None:
    """Create-or-update both structured indexes using workspace credentials."""
    s = get_settings()
    client = SearchIndexClient(endpoint=s.search_endpoint, credential=DefaultAzureCredential())
    client.create_or_update_index(build_catalog_index(s.search_index_catalog))
    client.create_or_update_index(build_facts_index(s.search_index_facts))


# ── Validation ────────────────────────────────────────────────────────────────


def _validate_catalog(doc_id: str, entries: list[FundCatalogEntry]) -> None:
    if not entries:
        raise ValueError(f"replace_catalog: empty batch for doc_id={doc_id!r}")
    wrong = [e.id for e in entries if e.doc_id != doc_id]
    if wrong:
        raise ValueError(
            f"replace_catalog: entries with wrong doc_id (expected {doc_id!r}): {wrong}"
        )
    ids = [e.id for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError(f"replace_catalog: duplicate ids in batch: {ids}")
    orders = sorted(e.toc_order for e in entries)
    if orders[0] != 1 or orders != list(range(1, len(orders) + 1)):
        raise ValueError(
            f"replace_catalog: toc_order must be contiguous starting at 1; got {orders}"
        )


def _validate_facts(doc_id: str, facts: list[EvaluationFact]) -> None:
    if not facts:
        raise ValueError(f"replace_facts: empty batch for doc_id={doc_id!r}")
    wrong_doc = [f.id for f in facts if f.doc_id != doc_id]
    if wrong_doc:
        raise ValueError(
            f"replace_facts: facts with wrong doc_id (expected {doc_id!r}): {wrong_doc}"
        )
    ids = [f.id for f in facts]
    if len(ids) != len(set(ids)):
        raise ValueError(f"replace_facts: duplicate ids in batch: {ids}")
    bad_prov = [f.id for f in facts if not f.source_chunk_id]
    if bad_prov:
        raise ValueError(
            f"replace_facts: missing provenance (source_chunk_id) for: {bad_prov}"
        )


# ── Upload helpers ────────────────────────────────────────────────────────────


def _escape_odata(value: str) -> str:
    return value.replace("'", "''")


def _fetch_existing_keys(client: SearchClient, doc_id: str) -> list[str]:
    results = client.search(
        search_text="*",
        filter=f"doc_id eq '{_escape_odata(doc_id)}'",
        select=["id"],
    )
    return [r["id"] for r in results]


def _delete_keys(client: SearchClient, keys: list[str]) -> None:
    for i in range(0, len(keys), _BATCH):
        batch = [{"id": k} for k in keys[i : i + _BATCH]]
        results = client.delete_documents(documents=batch)
        _check_results(results, "delete")


def _upload_docs(client: SearchClient, docs: list[dict]) -> None:
    for i in range(0, len(docs), _BATCH):
        results = client.upload_documents(documents=docs[i : i + _BATCH])
        _check_results(results, "upload")


def _check_results(results: list, operation: str) -> None:
    failed = [r for r in results if not r.succeeded]
    if failed:
        details = "; ".join(f"{r.key}: {r.error_message}" for r in failed)
        raise RuntimeError(f"Partial {operation} failure — {details}")


# ── Public replacement functions ──────────────────────────────────────────────


def replace_catalog(doc_id: str, entries: list[FundCatalogEntry], client: SearchClient) -> None:
    """Replace all catalog documents for *doc_id* with *entries*.

    Safety: validate locally → fetch existing keys → upload new set →
    verify IndexingResults → delete only stale old keys.
    If upload raises or returns any failed result, zero delete calls.
    """
    _validate_catalog(doc_id, entries)

    existing_keys = set(_fetch_existing_keys(client, doc_id))
    new_keys = {encode_search_key(e.id) for e in entries}

    docs = [
        {
            "id": encode_search_key(e.id),
            "fund_id": e.fund_id,
            "doc_id": e.doc_id,
            "year": e.year,
            "toc_order": e.toc_order,
            "canonical_name": e.canonical_name,
            "aliases": e.aliases,
            "ministry": e.ministry,
            "fund_scale": e.fund_scale,
            "start_page_printed": e.start_page_printed,
            "end_page_printed": e.end_page_printed,
            "start_page_physical": e.start_page_physical,
            "end_page_physical": e.end_page_physical,
            "source_page_physical": e.source_page_physical,
        }
        for e in entries
    ]
    _upload_docs(client, docs)

    stale_keys = sorted(existing_keys - new_keys)
    if stale_keys:
        _delete_keys(client, stale_keys)


def replace_facts(doc_id: str, facts: list[EvaluationFact], client: SearchClient) -> None:
    """Replace all fact documents for *doc_id* with *facts*.

    Safety: validate locally → fetch existing keys → upload new set →
    verify IndexingResults → delete only stale old keys.
    If upload raises or returns any failed result, zero delete calls.
    """
    _validate_facts(doc_id, facts)

    existing_keys = set(_fetch_existing_keys(client, doc_id))
    new_keys = {encode_search_key(f.id) for f in facts}

    docs = [
        {
            "id": encode_search_key(f.id),
            "fund_id": f.fund_id,
            "fund_name": f.fund_name,
            "doc_id": f.doc_id,
            "year": f.year,
            "ministry": f.ministry,
            "fact_type": f.fact_type,
            "metric_code": f.metric_code,
            "metric_name": f.metric_name,
            "metric_value": f.metric_value,
            "unit": f.unit,
            "score": f.score,
            "max_score": f.max_score,
            "pre_grade": f.pre_grade,
            "final_grade": f.final_grade,
            "grade": f.grade,
            "grade_rank": f.grade_rank,
            "adjustment": f.adjustment,
            "source_scope": f.source_scope,
            "population_scope": f.population_scope,
            "source_chunk_id": f.source_chunk_id,
            "source_page_physical": f.source_page_physical,
            "source_section_path": f.source_section_path,
            "source_text": f.source_text,
        }
        for f in facts
    ]
    _upload_docs(client, docs)

    stale_keys = sorted(existing_keys - new_keys)
    if stale_keys:
        _delete_keys(client, stale_keys)
