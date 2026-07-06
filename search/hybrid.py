from __future__ import annotations

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from pydantic import BaseModel

from config.settings import get_settings
from ingest.embedder import embed_texts


class SearchHit(BaseModel):
    content: str
    section_path: str
    page_physical: int
    chunk_type: str


def hybrid_search(index_name: str, query: str, top: int = 5) -> list[SearchHit]:
    s = get_settings()
    vector = embed_texts([query])[0]
    client = SearchClient(
        endpoint=s.search_endpoint, index_name=index_name, credential=DefaultAzureCredential()
    )
    results = client.search(
        search_text=query,
        vector_queries=[
            VectorizedQuery(vector=vector, k_nearest_neighbors=top, fields="content_vector")
        ],
        query_type="semantic",
        semantic_configuration_name="sem",
        top=top,
    )
    hits: list[SearchHit] = []
    for r in results:
        hits.append(
            SearchHit(
                content=r["content"],
                section_path=r.get("section_path", ""),
                page_physical=r.get("page_physical", 0),
                chunk_type=r.get("chunk_type", ""),
            )
        )
    return hits
