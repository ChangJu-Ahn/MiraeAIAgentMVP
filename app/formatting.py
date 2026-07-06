from __future__ import annotations

import re

from agent.tools import RetrievedSource, TraceStep


def format_reasoning_step(step: TraceStep) -> str:
    return f'{step.tool}("{step.query}") → {step.n_hits}건 검색'


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
