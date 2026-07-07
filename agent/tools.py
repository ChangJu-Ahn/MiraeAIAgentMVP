from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, Field

from config.settings import get_settings
from search.hybrid import hybrid_search


class RetrievedSource(BaseModel):
    n: int
    index: str
    section_path: str
    page_physical: int
    chunk_type: str
    snippet: str
    score: float = 0.0


class TraceStep(BaseModel):
    tool: str
    query: str
    n_hits: int


class TraceRecorder(BaseModel):
    steps: list[TraceStep] = Field(default_factory=list)
    sources: list[RetrievedSource] = Field(default_factory=list)


def _run_tool(
    recorder: TraceRecorder, tool_name: str, index_name: str, query: str, top: int = 5
) -> str:
    hits = hybrid_search(index_name, query, top=top)
    recorder.steps.append(TraceStep(tool=tool_name, query=query, n_hits=len(hits)))
    if not hits:
        return "검색 결과 없음"
    lines: list[str] = []
    for h in hits:
        n = len(recorder.sources) + 1
        recorder.sources.append(
            RetrievedSource(
                n=n,
                index=index_name,
                section_path=h.section_path,
                page_physical=h.page_physical,
                chunk_type=h.chunk_type,
                snippet=h.content[:300],
                score=h.score,
            )
        )
        lines.append(f"[출처 {n}] ({h.section_path}, p.{h.page_physical})\n{h.content[:500]}")
    return "\n\n".join(lines)


def make_search_tools(recorder: TraceRecorder) -> list[Callable[..., str]]:
    settings = get_settings()

    def search_narrative(query: str) -> str:
        """기금운용평가보고서의 서술형 본문(평가 개요·총평·정성 설명 등)에서 검색합니다.

        Args:
            query: 한국어 검색 질의.
        """
        return _run_tool(recorder, "search_narrative", settings.search_index_narrative, query)

    def search_tables(query: str) -> str:
        """기금운용평가보고서의 표(등급·점수·수익률 등 수치/정형 데이터)에서 검색합니다.

        Args:
            query: 한국어 검색 질의.
        """
        return _run_tool(recorder, "search_tables", settings.search_index_table, query)

    return [search_narrative, search_tables]
