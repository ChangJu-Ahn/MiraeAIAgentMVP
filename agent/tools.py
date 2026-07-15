from __future__ import annotations

from functools import wraps
import re
from typing import Callable, Literal

from pydantic import BaseModel, Field

from config.settings import get_settings
from ingest.corpus import CORPUS
from search.hybrid import hybrid_search
from search import structured as _structured


class RetrievedSource(BaseModel):
    n: int
    index: str
    section_path: str
    page_physical: int
    chunk_type: str
    snippet: str
    score: float = 0.0
    source_chunk_id: str | None = None


class TraceStep(BaseModel):
    tool: str
    query: str
    n_hits: int
    odata_filter: str | None = None


class TraceRecorder(BaseModel):
    steps: list[TraceStep] = Field(default_factory=list)
    sources: list[RetrievedSource] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    requested_years: list[int] = Field(default_factory=list, exclude=True)
    requested_doc_type: str | None = Field(default=None, exclude=True)


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


_QUERY_TERM_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def _query_excerpt(content: str, query: str, limit: int) -> str:
    if len(content) <= limit:
        return content

    terms = sorted(
        {term.casefold() for term in _QUERY_TERM_RE.findall(query)},
        key=len,
        reverse=True,
    )
    folded = content.casefold()
    candidates: set[int] = set()
    for term in terms:
        offset = 0
        while (position := folded.find(term, offset)) >= 0:
            candidates.add(min(max(0, position - limit // 3), len(content) - limit))
            offset = position + len(term)

    if not candidates:
        return content[:limit]

    def score(start: int) -> tuple[int, int, int]:
        window = folded[start : start + limit]
        matched = [term for term in terms if term in window]
        weighted_occurrences = sum(
            len(term) * window.count(term) for term in matched
        )
        return len(matched), weighted_occurrences, -start

    best_start = max(candidates, key=score)
    return content[best_start : best_start + limit]


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
        source_excerpt = _query_excerpt(h.content, query, 300)
        agent_excerpt = _query_excerpt(h.content, query, 1500)
        n = len(recorder.sources) + 1
        recorder.sources.append(
            RetrievedSource(
                n=n,
                index=index_name,
                section_path=h.section_path,
                page_physical=h.page_physical,
                chunk_type=h.chunk_type,
                snippet=source_excerpt,
                score=h.score,
            )
        )
        lines.append(
            f"[출처 {n}] ({h.section_path}, p.{h.page_physical})\n{agent_excerpt}"
        )
    return "\n\n".join(lines)



def make_search_tools(recorder: TraceRecorder) -> list[Callable[..., str]]:
    settings = get_settings()
    missing_documents: set[tuple[int, str]] = set()
    requested_documents = {
        (year, recorder.requested_doc_type)
        for year in recorder.requested_years
        if recorder.requested_doc_type is not None
    }

    def _document_exists(year: int, doc_type: str) -> bool:
        return any(
            document.year == year and document.doc_type == doc_type
            for document in CORPUS
        )

    def _document_label(year: int, doc_type: str) -> str:
        type_label = {
            "report": "기금운용평가보고서",
            "guideline": "기금운용평가지침",
        }.get(doc_type, doc_type)
        return f"{year}회계연도 {type_label}"

    def _record_manifest_source(year: int, doc_type: str) -> int:
        source_chunk_id = f"corpus-manifest/{year}/{doc_type}"
        for existing in recorder.sources:
            if existing.source_chunk_id == source_chunk_id:
                return existing.n

        available = sorted(
            document.year
            for document in CORPUS
            if document.doc_type == doc_type
        )
        available_text = ", ".join(map(str, available)) or "없음"
        label = _document_label(year, doc_type)
        n = len(recorder.sources) + 1
        recorder.sources.append(
            RetrievedSource(
                n=n,
                index="corpus-manifest",
                section_path="제공 문서 목록",
                page_physical=0,
                chunk_type="manifest",
                snippet=(
                    f"제공된 corpus에 {label}는 없습니다. "
                    f"제공된 {doc_type} 연도: {available_text}."
                ),
                score=1.0,
                source_chunk_id=source_chunk_id,
            )
        )
        return n

    def _missing_document_message(year: int, doc_type: str) -> str:
        missing_documents.add((year, doc_type))
        cite_n = _record_manifest_source(year, doc_type)
        return (
            f"[출처 {cite_n}] corpus manifest 확인 결과, "
            f"{_document_label(year, doc_type)}는 제공된 corpus에 없습니다. "
            "해당 연도의 값을 다른 연도 문서에서 추론하거나 대체하지 말고, "
            "제공된 자료에서 확인할 수 없다고 답하세요."
        )

    def _guard_document_search(
        *,
        tool_name: str,
        query: str,
        year: int | None,
        doc_type: str | None,
        odata_filter: str | None,
    ) -> str | None:
        if year is not None and doc_type is not None:
            if not _document_exists(year, doc_type):
                recorder.steps.append(
                    TraceStep(
                        tool=tool_name,
                        query=query,
                        n_hits=0,
                        odata_filter=odata_filter,
                    )
                )
                return _missing_document_message(year, doc_type)

        if not missing_documents:
            return None

        requested_pair = (year, doc_type)
        is_requested_document = (
            year is not None
            and doc_type is not None
            and requested_pair in requested_documents
        )
        if is_requested_document:
            return None

        recorder.steps.append(
            TraceStep(
                tool=tool_name,
                query=query,
                n_hits=0,
                odata_filter=odata_filter,
            )
        )
        labels = ", ".join(
            _document_label(year_value, type_value)
            for year_value, type_value in sorted(missing_documents)
        )
        cite_n = _record_manifest_source(*sorted(missing_documents)[0])
        return (
            f"[출처 {cite_n}] {labels}가 제공되지 않아 연도·문서유형 필터를 "
            "제거하거나 요청 범위 밖 문서로 넓히는 대체 검색을 차단했습니다. "
            "누락된 연도는 확인 불가로 공개하세요."
        )

    def _capture_evidence(tool: Callable[..., str]) -> Callable[..., str]:
        @wraps(tool)
        def wrapped(*args, **kwargs) -> str:
            output = tool(*args, **kwargs)
            recorder.evidence.append(output)
            return output

        return wrapped

    def _record_catalog_source(entries, year: int, ministry: str | None) -> int:
        source_chunk_id = f"catalog-list:{year}:{ministry or '*'}"
        for existing in recorder.sources:
            if existing.source_chunk_id == source_chunk_id:
                return existing.n

        names: list[str] = []
        for entry in entries:
            label = entry.canonical_name
            if entry.aliases:
                label += f" (별칭: {', '.join(entry.aliases)})"
            names.append(label)
        scope = f"{ministry} 소관 " if ministry else ""
        n = len(recorder.sources) + 1
        recorder.sources.append(
            RetrievedSource(
                n=n,
                index=settings.search_index_catalog,
                section_path=f"{year}년 {scope}평가 대상 기금 TOC",
                page_physical=min(entry.source_page_physical for entry in entries),
                chunk_type="catalog",
                snippet=(
                    f"{year}년 {scope}평가 대상 기금 전체 목록 ({len(entries)}개): "
                    + ", ".join(names)
                ),
                source_chunk_id=source_chunk_id,
            )
        )
        return n

    # ── Helper: record a fact source, dedup by source_chunk_id ──────────
    def _record_fact_source(fact) -> int:
        """Append a fact-based source to the recorder, returning citation number.

        If a source with the same ``source_chunk_id`` already exists, reuse
        its citation number without adding a duplicate.
        """
        for existing in recorder.sources:
            if existing.source_chunk_id == fact.source_chunk_id:
                return existing.n
        n = len(recorder.sources) + 1
        recorder.sources.append(
            RetrievedSource(
                n=n,
                index="evaluation-facts-index",
                section_path=fact.source_section_path,
                page_physical=fact.source_page_physical,
                chunk_type="fact",
                snippet=fact.source_text[:300],
                source_chunk_id=fact.source_chunk_id,
            )
        )
        return n

    def _format_fact_value(fact, *, include_grade: bool = True) -> str:
        parts: list[str] = []
        if fact.adjustment is not None:
            parts.append(f"{fact.adjustment:+g}")
        if fact.metric_value is not None:
            parts.append(f"지표값 {fact.metric_value:g}{fact.unit or ''}")
        if fact.score is not None:
            score = f"{fact.score:g}"
            if fact.max_score is not None:
                score += f"/{fact.max_score:g}"
            parts.append(f"평가점수 {score}")
        if include_grade:
            final_grade = fact.final_grade or fact.grade
            if fact.pre_grade is not None and final_grade is not None:
                parts.append(f"사전등급 {fact.pre_grade} → 최종등급 {final_grade}")
            elif final_grade is not None:
                parts.append(f"최종등급 {final_grade}")
        return ", ".join(parts) or "데이터 없음"

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
        blocked = _guard_document_search(
            tool_name="search_narrative",
            query=query,
            year=year,
            doc_type=doc_type,
            odata_filter=f,
        )
        if blocked is not None:
            return blocked
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
        blocked = _guard_document_search(
            tool_name="search_tables",
            query=query,
            year=year,
            doc_type=doc_type,
            odata_filter=f,
        )
        if blocked is not None:
            return blocked
        return _run_tool(recorder, "search_tables", settings.search_index_table, query, odata_filter=f)

    # ── Structured catalog / aggregation closures ────────────────────────

    def list_funds(year: int, ministry: str | None = None) -> str:
        """평가 대상 기금 전체 목록을 반환합니다 (결정적 카탈로그 기반).

        Args:
            year: 회계연도(예: 2025).
            ministry: 소관부처로 필터링(예: '기획재정부'). 생략하면 전체.
        """
        if not (2000 <= year <= 2099):
            return f"연도 오류: {year}은(는) 유효한 회계연도가 아닙니다 (2000~2099)."
        entries = _structured.list_funds(year=year, ministry=ministry)
        query_summary = f"year={year}"
        if ministry:
            query_summary += f", ministry={ministry}"
        recorder.steps.append(
            TraceStep(tool="list_funds", query=query_summary, n_hits=len(entries))
        )
        if not entries:
            return f"{year}년 평가 대상 기금이 없습니다."
        cite_n = _record_catalog_source(entries, year, ministry)
        lines = [f"## {year}년 평가 대상 기금 ({len(entries)}개) [출처 {cite_n}]"]
        if ministry:
            lines[0] += f" — {ministry}"
        for e in entries:
            lines.append(f"{e.toc_order}. {e.canonical_name} ({e.ministry})")
        return "\n".join(lines)

    def resolve_fund(name: str, year: int | None = None) -> str:
        """기금명 또는 별칭으로 정식 기금 정보를 조회합니다.

        Args:
            name: 기금명 또는 별칭(예: '국민연금기금', '사학연금기금').
            year: 회계연도. 생략하면 전체 연도에서 탐색.
        """
        if year is not None and not (2000 <= year <= 2099):
            return f"연도 오류: {year}은(는) 유효한 회계연도가 아닙니다 (2000~2099)."
        entry = _structured.resolve_fund(name=name, year=year)
        query_summary = f"name={name}"
        if year is not None:
            query_summary += f", year={year}"
        recorder.steps.append(
            TraceStep(tool="resolve_fund", query=query_summary, n_hits=1 if entry else 0)
        )
        if entry is None:
            return f"'{name}'에 해당하는 기금을 찾을 수 없습니다."
        aliases_str = ", ".join(entry.aliases) if entry.aliases else "없음"
        return (
            f"기금명: {entry.canonical_name}\n"
            f"fund_id: {entry.fund_id}\n"
            f"연도: {entry.year}\n"
            f"소관부처: {entry.ministry}\n"
            f"별칭: {aliases_str}"
        )

    def get_fund_evaluations(fund_name: str, year: int, metric: str | None = None) -> str:
        """특정 기금의 평가 결과(점수·등급)를 구조화된 팩트로 반환합니다.

        자산운용 성과를 명시적으로 조회하면 annual overall_grade 평가완료
        모집단 내 Python 결정적 순위도 함께 반환합니다.

        Args:
            fund_name: 기금명(예: '국민연금기금'). resolve_fund로 확인한 정식 명칭 권장.
            year: 회계연도(예: 2025).
            metric: 특정 평가지표 코드 또는 이름으로 필터링. 생략하면 전체 지표.
        """
        if not (2000 <= year <= 2099):
            return f"연도 오류: {year}은(는) 유효한 회계연도가 아닙니다 (2000~2099)."
        query_summary = f"fund_name={fund_name}, year={year}"
        if metric:
            query_summary += f", metric={metric}"
        blocked = _guard_document_search(
            tool_name="get_fund_evaluations",
            query=query_summary,
            year=year,
            doc_type="report",
            odata_filter=None,
        )
        if blocked is not None:
            return blocked
        facts = _structured.get_fund_evaluations(fund_name=fund_name, year=year, metric=metric)
        recorder.steps.append(
            TraceStep(tool="get_fund_evaluations", query=query_summary, n_hits=len(facts))
        )
        if not facts:
            return f"'{fund_name}'의 {year}년 평가 데이터가 없습니다."
        lines = [f"## {fund_name} — {year}년 평가 결과"]
        for f in facts:
            cite_n = _record_fact_source(f)
            include_grade = not (
                metric is not None
                and f.metric_code == "asset_management_performance"
            )
            lines.append(
                f"- {f.metric_name}: "
                f"{_format_fact_value(f, include_grade=include_grade)} "
                f"[출처 {cite_n}]"
            )

        adjustments = [
            fact.adjustment for fact in facts if fact.adjustment is not None
        ]
        if metric is not None and len(adjustments) == len(facts):
            lines.append(f"- 총 가감점: {sum(adjustments):+g}")

        performance_fact = next(
            (
                fact
                for fact in facts
                if fact.metric_code == "asset_management_performance"
            ),
            None,
        )
        if metric is not None and performance_fact is not None:
            ranking = _structured.fund_analytics(
                operation="rank",
                years=[year],
                metric="asset_management_performance",
                population="evaluated",
                order="desc",
                limit=100,
            )
            recorder.steps.append(
                TraceStep(
                    tool="fund_analytics",
                    query=(
                        f"operation=rank, years={ranking.years}, "
                        "metric=asset_management_performance, "
                        "population=evaluated, grade=None, order=desc, limit=100"
                    ),
                    n_hits=len(ranking.rows),
                )
            )
            target_rank = None
            target_citation = None
            for rank, row in enumerate(ranking.rows, 1):
                ranked_fact = row.facts[0]
                cite_n = _record_fact_source(ranked_fact)
                if row.fund_id == performance_fact.fund_id:
                    target_rank = rank
                    target_citation = cite_n
            if target_rank is not None:
                population_count = ranking.summaries[0].population_count
                lines.append(
                    "- 평가완료 모집단 내 순위: "
                    f"{population_count}개 중 {target_rank}위 "
                    "(annual overall_grade와 자산운용 성과 fact의 교집합, "
                    f"내림차순) [출처 {target_citation}]"
                )
        return "\n".join(lines)

    def aggregate_evaluations(
        year: int,
        metric: str | None = None,
        order: str = "desc",
        limit: int = 3,
        ministry: str | None = None,
        per_fund: bool = False,
    ) -> str:
        """기금 간 평가 점수·등급 순위를 결정적으로 집계합니다.

        전체 평가 대상 기금(population)에 대해 완전한 커버리지 정보를 포함합니다.
        반복적 시맨틱 검색(top-k) 대신 이 도구를 사용하세요.

        Args:
            year: 회계연도(예: 2025).
            metric: 평가지표 코드 또는 이름(예: 'quantitative_total', '계량지표 합계').
            order: 정렬 순서 — 'desc'(높은 순) 또는 'asc'(낮은 순). 기본값 'desc'.
            limit: 반환할 최대 기금 수(1~100). 기본값 3.
            ministry: 소관부처 필터. 생략하면 전체.
            per_fund: True이면 기금별로 limit만큼 지표를 반환.
        """
        if not (2000 <= year <= 2099):
            return f"연도 오류: {year}은(는) 유효한 회계연도가 아닙니다 (2000~2099)."
        if order not in ("asc", "desc"):
            return f"정렬 오류: order는 'asc' 또는 'desc'만 가능합니다 (입력값: '{order}')."
        if not (1 <= limit <= 100):
            return f"limit 오류: 1~100 범위여야 합니다 (입력값: {limit})."

        agg = _structured.aggregate_evaluations(
            year=year, metric=metric, order=order, limit=limit,
            ministry=ministry, per_fund=per_fund,
        )

        query_summary = f"year={year}, order={order}, limit={limit}"
        if metric:
            query_summary += f", metric={metric}"
        if ministry:
            query_summary += f", ministry={ministry}"
        recorder.steps.append(
            TraceStep(tool="aggregate_evaluations", query=query_summary, n_hits=len(agg.rows))
        )

        lines: list[str] = []
        order_label = "상위" if order == "desc" else "하위"
        title = f"## {year}년 기금 평가 순위 ({order_label} {agg.limit})"
        if agg.metric:
            title += f" — {agg.metric}"
        if agg.ministry:
            title += f" ({agg.ministry})"
        lines.append(title)
        lines.append(f"전체 대상: {agg.population_count}개 기금 | 데이터 보유: {agg.matched_count}개")

        if agg.missing_funds:
            lines.append(f"⚠ 데이터 미포함 기금 ({len(agg.missing_funds)}개): {', '.join(agg.missing_funds)}")

        if not agg.rows:
            lines.append("해당 조건의 순위 데이터가 없습니다.")
            return "\n".join(lines)

        if per_fund:
            # Group by fund
            current_fund = None
            for f in agg.rows:
                if f.fund_name != current_fund:
                    current_fund = f.fund_name
                    lines.append(f"\n### {current_fund}")
                cite_n = _record_fact_source(f)
                if f.score is not None:
                    score_str = f"{f.score}/{f.max_score}" if f.max_score else str(f.score)
                    lines.append(f"  - {f.metric_name}: {score_str} [출처 {cite_n}]")
                elif f.grade is not None:
                    lines.append(f"  - {f.metric_name}: {f.grade} [출처 {cite_n}]")
        else:
            for rank, f in enumerate(agg.rows, 1):
                cite_n = _record_fact_source(f)
                if f.score is not None:
                    score_str = f"{f.score}/{f.max_score}" if f.max_score else str(f.score)
                    lines.append(f"{rank}. {f.fund_name}: {score_str} [출처 {cite_n}]")
                elif f.grade is not None:
                    lines.append(f"{rank}. {f.fund_name}: {f.grade} [출처 {cite_n}]")

        return "\n".join(lines)

    def fund_analytics(
        operation: Literal[
            "rank", "distribution", "compare_years", "grade_changes", "maintained_grade"
        ],
        years: list[int],
        metric: str = "overall_grade",
        population: Literal["metric", "evaluated"] = "metric",
        grade: str | None = None,
        order: Literal["asc", "desc"] = "desc",
        limit: int = 3,
        ministry: str | None = None,
    ) -> str:
        """정해진 Python 연산으로 순위·분포·연도비교·등급변동·교집합을 계산합니다.

        Args:
            operation: rank, distribution, compare_years, grade_changes,
                maintained_grade 중 하나.
            years: 분석할 회계연도 목록. rank/distribution은 1개,
                grade_changes는 2개, 비교/유지는 2개 이상.
            metric: 지표 코드 또는 이름. 종합등급은 overall_grade,
                계량 성과점수는 asset_management_performance.
            population: metric은 해당 지표의 기본 모집단, evaluated는
                annual overall_grade가 있는 평가완료 기금과의 교집합.
                계량 성과의 평가완료 기금 내 순위에는 evaluated를 사용.
            grade: maintained_grade에서 유지 여부를 확인할 등급(예: 탁월).
            order: rank 정렬 순서. desc는 높은 순, asc는 낮은 순.
            limit: rank 결과 수(1~100).
            ministry: 소관부처 필터.
        """
        try:
            result = _structured.fund_analytics(
                operation=operation,
                years=years,
                metric=metric,
                population=population,
                grade=grade,
                order=order,
                limit=limit,
                ministry=ministry,
            )
        except ValueError as exc:
            return f"분석 오류: {exc}"

        recorder.steps.append(
            TraceStep(
                tool="fund_analytics",
                query=(
                    f"operation={operation}, years={result.years}, metric={metric}, "
                    f"population={population}, grade={grade}, order={order}, "
                    f"limit={limit}"
                ),
                n_hits=len(result.rows),
            )
        )

        basis_labels = {
            "catalog": "TOC 카탈로그",
            "annual_summary": "연간 종합평가표",
            "metric_available": "지표 제공 기금",
        }
        lines = [
            f"## Python 결정적 집계 — {operation} ({', '.join(map(str, result.years))})",
            f"지표: {result.metric}",
        ]
        for summary in result.summaries:
            lines.append(
                f"- {summary.year}년: 모집단 {summary.population_count}개 "
                f"(TOC {summary.catalog_count}개, 모집단 기준: "
                f"{basis_labels[summary.population_basis]}), 데이터 {summary.matched_count}개"
            )
            include_rank_grades = not (
                operation == "rank"
                and result.metric == "asset_management_performance"
            )
            if summary.grade_distribution and include_rank_grades:
                distribution = ", ".join(
                    f"{name} {count}개"
                    for name, count in summary.grade_distribution.items()
                )
                lines.append(f"  등급 분포: {distribution}")
            if summary.missing_funds:
                lines.append(f"  제외/누락: {', '.join(summary.missing_funds)}")

        if result.common_count is not None:
            lines.append(f"공통 비교 기금: {result.common_count}개")
        if result.unchanged_count is not None:
            lines.append(f"첫해와 마지막 해 값 유지: {result.unchanged_count}개")
        if not result.rows:
            lines.append("해당 조건의 결과가 없습니다.")
            return "\n".join(lines)

        if operation == "distribution":
            groups: dict[str, list[str]] = {}
            for row in result.rows:
                fact = row.facts[0]
                cite_n = _record_fact_source(fact)
                groups.setdefault(fact.grade or "등급 없음", []).append(
                    f"{row.fund_name} [출처 {cite_n}]"
                )
            for grade_name, funds in groups.items():
                lines.append(f"- {grade_name}: {', '.join(funds)}")
            return "\n".join(lines)

        if operation == "rank":
            include_grade = result.metric != "asset_management_performance"
            for rank, row in enumerate(result.rows, 1):
                fact = row.facts[0]
                cite_n = _record_fact_source(fact)
                lines.append(
                    f"{rank}. {row.fund_name}: "
                    f"{_format_fact_value(fact, include_grade=include_grade)} "
                    f"[출처 {cite_n}]"
                )
            return "\n".join(lines)

        direction_labels = {"up": "상승", "down": "하락", "same": "유지", None: "비교 불가"}
        for row in result.rows:
            values: list[str] = []
            for fact in row.facts:
                cite_n = _record_fact_source(fact)
                values.append(
                    f"{fact.year}년 {_format_fact_value(fact)} [출처 {cite_n}]"
                )
            lines.append(
                f"- {row.fund_name}: {' → '.join(values)} "
                f"({direction_labels[row.direction]})"
            )
        return "\n".join(lines)

    return [
        search_narrative,
        search_tables,
        _capture_evidence(list_funds),
        _capture_evidence(resolve_fund),
        _capture_evidence(get_fund_evaluations),
        _capture_evidence(aggregate_evaluations),
        _capture_evidence(fund_analytics),
    ]
