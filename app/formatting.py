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
    lines: list[str] = ["# 🐞 디버그 트레이스"]
    for index, (question, steps, sources) in enumerate(rounds, 1):
        lines.append(f"\n## 라운드 {index}")
        lines.append(f"**질의:** {question}")
        lines.append("\n**도구 호출:**")
        if steps:
            for step in steps:
                odata_filter = (
                    f" · 필터: `{step.odata_filter}`"
                    if getattr(step, "odata_filter", None)
                    else " · 필터: 없음"
                )
                lines.append(
                    f'- `{step.tool}("{step.query}")` → {step.n_hits}건{odata_filter}'
                )
        else:
            lines.append("- (없음)")

        lines.append("\n**AI Search 결과 (하이브리드 + 리랭킹, 관련도순):**")
        if sources:
            for source in sources:
                lines.append(
                    f"- **[출처 {source.n}]** `{source.index}` · "
                    f"{source.section_path} · p.{source.page_physical} · "
                    f"**관련도 {source.score:.2f}**"
                )
                lines.append(f"  > {source.snippet[:160]}")
        else:
            lines.append("- (검색 결과 없음)")

    lines.append("\n## 최종 인용")
    if cited:
        lines.extend(
            f"- **[출처 {source.n}]** {source.section_path} · "
            f"p.{source.page_physical} · 관련도 {source.score:.2f}"
            for source in cited
        )
    else:
        lines.append("- (모델이 [출처 N] 형식으로 인용하지 않음)")

    if raw_trace:
        lines.extend(
            [
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
        )
    return "\n".join(lines)
