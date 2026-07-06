from __future__ import annotations

from agent.tools import RetrievedSource, TraceStep


def format_reasoning_step(step: TraceStep) -> str:
    return f'{step.tool}("{step.query}") → {step.n_hits}건 검색'


def format_citations(sources: list[RetrievedSource]) -> str:
    if not sources:
        return ""
    lines = ["### 근거"]
    for s in sources:
        lines.append(f"- **[출처 {s.n}]** ({s.index}) {s.section_path} · p.{s.page_physical}")
    return "\n".join(lines)
