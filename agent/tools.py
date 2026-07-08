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
    odata_filter: str | None = None


class TraceRecorder(BaseModel):
    steps: list[TraceStep] = Field(default_factory=list)
    sources: list[RetrievedSource] = Field(default_factory=list)


def _esc(v: str) -> str:
    return v.replace("'", "''")


def _build_odata_filter(
    year: int | None = None,
    doc_type: str | None = None,
    fund_name: str | None = None,
    fund_scale: str | None = None,
) -> str | None:
    clauses: list[str] = []
    if year is not None:
        clauses.append(f"year eq {int(year)}")
    if doc_type:
        clauses.append(f"doc_type eq '{_esc(doc_type)}'")
    if fund_name:
        clauses.append(f"fund_name eq '{_esc(fund_name)}'")
    if fund_scale:
        clauses.append(f"fund_scale eq '{_esc(fund_scale)}'")
    return " and ".join(clauses) or None


def _run_tool(
    recorder: TraceRecorder,
    tool_name: str,
    index_name: str,
    query: str,
    top: int = 5,
    odata_filter: str | None = None,
) -> str:
    hits = hybrid_search(index_name, query, top=top, odata_filter=odata_filter)
    recorder.steps.append(
        TraceStep(tool=tool_name, query=query, n_hits=len(hits), odata_filter=odata_filter)
    )
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

    def search_narrative(
        query: str,
        year: int | None = None,
        doc_type: str | None = None,
        fund_name: str | None = None,
        fund_scale: str | None = None,
    ) -> str:
        """기금운용평가보고서의 서술형 본문에서 검색합니다.

        Args:
            query: 한국어 검색 질의.
            year: 회계연도(예: 2022). 질문에 연도가 명시되면 채우세요.
            doc_type: 'report'(보고서) 또는 'guideline'(지침).
            fund_name: 개별 기금명(예: 국민연금기금).
            fund_scale: '대형중소형' 또는 '대규모'.
        """
        f = _build_odata_filter(year, doc_type, fund_name, fund_scale)
        return _run_tool(recorder, "search_narrative", settings.search_index_narrative, query, odata_filter=f)

    def search_tables(
        query: str,
        year: int | None = None,
        doc_type: str | None = None,
        fund_name: str | None = None,
        fund_scale: str | None = None,
    ) -> str:
        """기금운용평가보고서의 표(수치/정형 데이터)에서 검색합니다.

        Args:
            query: 한국어 검색 질의.
            year: 회계연도(예: 2022).
            doc_type: 'report' 또는 'guideline'.
            fund_name: 개별 기금명.
            fund_scale: '대형중소형' 또는 '대규모'.
        """
        f = _build_odata_filter(year, doc_type, fund_name, fund_scale)
        return _run_tool(recorder, "search_tables", settings.search_index_table, query, odata_filter=f)

    return [search_narrative, search_tables]
