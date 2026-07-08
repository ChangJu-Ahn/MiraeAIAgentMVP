from __future__ import annotations

import re

from agent.tools import RetrievedSource, TraceStep


def cited_sources(answer: str, sources: list[RetrievedSource]) -> list[RetrievedSource]:
    """Return only the sources actually referenced as [출처 N] in the answer."""
    nums = {int(m) for m in re.findall(r"\[출처\s*(\d+)\]", answer)}
    return [s for s in sources if s.n in nums]


def dedup_sources(sources: list[RetrievedSource], limit: int = 8) -> list[RetrievedSource]:
    """(섹션 경로, 페이지) 기준으로 중복을 제거하고 상위 limit개만 반환."""
    seen: set[tuple[str, int]] = set()
    out: list[RetrievedSource] = []
    for s in sources:
        key = (s.section_path, s.page_physical)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def format_citations(sources: list[RetrievedSource], heading: str = "근거") -> str:
    if not sources:
        return ""
    lines = [f"### {heading}"]
    for s in sources:
        lines.append(f"- **[출처 {s.n}]** ({s.index}) {s.section_path} · p.{s.page_physical}")
    return "\n".join(lines)


def format_debug(
    rounds: list[tuple[str, list[TraceStep], list[RetrievedSource]]],
    cited: list[RetrievedSource],
    raw_trace: str = "",
) -> str:
    """디버그 사이드바용 마크다운.

    라운드별로 (1) 에이전트가 호출한 검색 도구 트레이스, (2) AI Search가
    하이브리드+시맨틱 리랭킹을 거쳐 반환한 전체 결과와 관련도 점수, 그리고
    마지막에 (3) 답변이 실제 인용한 최종 근거를 함께 보여준다.
    raw_trace(OpenTelemetry 표준 JSON)가 주어지면 맨 아래에 접힌 상태로 덧붙인다.
    """
    lines: list[str] = ["# 🐞 디버그 트레이스"]
    for i, (question, steps, sources) in enumerate(rounds, 1):
        lines.append(f"\n## 라운드 {i}")
        lines.append(f"**질의:** {question}")
        lines.append("\n**도구 호출:**")
        if steps:
            for st in steps:
                flt = f" · 필터: `{st.odata_filter}`" if getattr(st, "odata_filter", None) else " · 필터: 없음"
                lines.append(f'- `{st.tool}("{st.query}")` → {st.n_hits}건{flt}')
        else:
            lines.append("- (없음)")
        lines.append("\n**AI Search 결과 (하이브리드 + 리랭킹, 관련도순):**")
        if sources:
            for s in sources:
                lines.append(
                    f"- **[출처 {s.n}]** `{s.index}` · {s.section_path} · "
                    f"p.{s.page_physical} · **관련도 {s.score:.2f}**"
                )
                lines.append(f"  > {s.snippet[:160]}")
        else:
            lines.append("- (검색 결과 없음)")
    lines.append("\n## 최종 인용")
    if cited:
        lines += [
            f"- **[출처 {s.n}]** {s.section_path} · p.{s.page_physical} · 관련도 {s.score:.2f}"
            for s in cited
        ]
    else:
        lines.append("- (모델이 [출처 N] 형식으로 인용하지 않음)")
    if raw_trace:
        lines += [
            "\n---",
            "<details>",
            "<summary>🔬 Raw OpenTelemetry Trace (OTel 표준 포맷)</summary>",
            "",
            "```json",
            raw_trace,
            "```",
            "",
            "</details>",
        ]
    return "\n".join(lines)


def format_source_docs(items: list[tuple[str, str]]) -> str:
    """원본 데이터소스 PDF 링크 블록. items=(라벨, URL). 없으면 빈 문자열."""
    if not items:
        return ""
    lines = ["📎 **원본 자료 (데이터소스)** — 클릭하면 원본 PDF를 새 탭에서 볼 수 있습니다:"]
    for label, url in items:
        lines.append(f"- [{label}]({url})")
    return "\n".join(lines)
