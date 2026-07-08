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
    score: float


def hybrid_search(
    index_name: str, query: str, top: int = 5, odata_filter: str | None = None
) -> list[SearchHit]:
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
        filter=odata_filter,
    )
    hits: list[SearchHit] = []
    for r in results:
        # 시맨틱 리랭커 관련도(0~4)를 우선 사용, 없으면 하이브리드 점수로 대체
        reranker = r.get("@search.reranker_score")
        score = reranker if reranker is not None else r["@search.score"]
        hits.append(
            SearchHit(
                content=r["content"],
                section_path=r.get("section_path", ""),
                page_physical=r.get("page_physical", 0),
                chunk_type=r.get("chunk_type", ""),
                score=score,
            )
        )
    return hits
