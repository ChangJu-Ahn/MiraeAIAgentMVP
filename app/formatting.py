from __future__ import annotations

import re

from agent.tools import RetrievedSource, TraceStep


def format_reasoning_step(step: TraceStep) -> str:
    return f'{step.tool}("{step.query}") → {step.n_hits}건 검색'


def cited_sources(answer: str, sources: list[RetrievedSource]) -> list[RetrievedSource]:
    """Return only the sources actually referenced as [출처 N] in the answer."""
    nums = {int(m) for m in re.findall(r"\[출처\s*(\d+)\]", answer)}
    return [s for s in sources if s.n in nums]


def format_citations(sources: list[RetrievedSource]) -> str:
    if not sources:
        return ""
    lines = ["### 근거"]
    for s in sources:
        lines.append(f"- **[출처 {s.n}]** ({s.index}) {s.section_path} · p.{s.page_physical}")
    return "\n".join(lines)
