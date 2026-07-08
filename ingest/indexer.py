from __future__ import annotations

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

from config.settings import get_settings
from ingest.models import Chunk

EMBED_DIM = 3072


def build_index(name: str) -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="ko.lucene"),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBED_DIM,
            vector_search_profile_name="hnsw-profile",
        ),
        SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="chunk_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SearchableField(name="section_path", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="doc_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="fund_name", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="fund_scale", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="year", type=SearchFieldDataType.Int32, filterable=True, facetable=True),
        SimpleField(name="page_physical", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(name="page_printed", type=SearchFieldDataType.Int32, filterable=True),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
    )
    semantic = SemanticSearch(
        default_configuration_name="sem",
        configurations=[
            SemanticConfiguration(
                name="sem",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="section_path"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ],
    )
    return SearchIndex(
        name=name, fields=fields, vector_search=vector_search, semantic_search=semantic
    )


def ensure_indexes() -> None:
    s = get_settings()
    client = SearchIndexClient(endpoint=s.search_endpoint, credential=DefaultAzureCredential())
    for name in (s.search_index_narrative, s.search_index_table):
        client.create_or_update_index(build_index(name))


def reset_indexes() -> None:
    """인덱스를 삭제 후 재생성한다.

    Azure AI Search는 기존 인덱스에서 필드를 삭제할 수 없어(업데이트로 필드 제거 불가),
    스키마에서 필드를 뺀 변경(예: year/fund_name 제거)을 반영하려면 재생성이 필요하다.
    삭제 후에는 반드시 재인제스트(upload_chunks)로 문서를 다시 채워야 한다.
    """
    s = get_settings()
    client = SearchIndexClient(endpoint=s.search_endpoint, credential=DefaultAzureCredential())
    for name in (s.search_index_narrative, s.search_index_table):
        try:
            client.delete_index(name)
        except Exception:  # noqa: BLE001 - 인덱스가 없으면 무시
            pass
        client.create_or_update_index(build_index(name))


def _chunk_to_doc(chunk: Chunk) -> dict:
    doc = {
        "id": chunk.id,
        "content": chunk.content,
        "content_vector": chunk.content_vector,
        "doc_id": chunk.doc_id,
        "chunk_type": chunk.chunk_type,
        "section_path": chunk.section_path,
        "page_physical": chunk.page_physical,
    }
    for k in ("year", "doc_type", "fund_name", "fund_scale", "page_printed"):
        v = getattr(chunk, k)
        if v is not None:
            doc[k] = v
    return doc


def upload_chunks(chunks: list[Chunk]) -> int:
    s = get_settings()
    cred = DefaultAzureCredential()
    buckets: dict[str, list[dict]] = {s.search_index_narrative: [], s.search_index_table: []}
    for c in chunks:
        if c.content_vector is None:
            raise ValueError(f"chunk {c.id} has no embedding")
        target = s.search_index_table if c.chunk_type == "table" else s.search_index_narrative
        buckets[target].append(_chunk_to_doc(c))
    total = 0
    for index_name, docs in buckets.items():
        if not docs:
            continue
        client = SearchClient(endpoint=s.search_endpoint, index_name=index_name, credential=cred)
        for i in range(0, len(docs), 1000):
            client.upload_documents(documents=docs[i : i + 1000])
        total += len(docs)
    return total

