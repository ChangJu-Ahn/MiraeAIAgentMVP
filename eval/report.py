from __future__ import annotations

from pydantic import BaseModel

METRICS = ["groundedness", "relevance", "retrieval", "coherence", "fluency"]


class EvalRow(BaseModel):
    id: str
    qtype: str
    question: str
    answer: str
    metrics: dict[str, float] = {}
    passed: dict[str, bool] = {}
    cited: bool = False
    refused: bool | None = None


def _rate(flags: list[bool]) -> float:
    return 100.0 * sum(1 for f in flags if f) / len(flags) if flags else 0.0


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_report(rows: list[EvalRow]) -> str:
    lines: list[str] = ["# 평가 리포트 (Foundry Evaluation)", ""]
    lines.append(f"- 총 문항: {len(rows)}")
    lines.append("")

    # 목표선 대비
    grounded_flags = [r.passed.get("groundedness", False) for r in rows if r.qtype != "원문부재"]
    cited_flags = [r.cited for r in rows if r.qtype != "원문부재"]
    refused_flags = [bool(r.refused) for r in rows if r.qtype == "원문부재"]
    acc = _rate(grounded_flags)
    cite = _rate(cited_flags)
    halluc = _rate(refused_flags)
    lines += [
        "## 목표선 대비",
        "| 지표 | 결과 | 목표 | 판정 |",
        "|---|---|---|---|",
        f"| 정확도(groundedness 통과율) | {acc:.1f}% | 80% | {'✅' if acc >= 80 else '❌'} |",
        f"| 근거 인용율 | {cite:.1f}% | 90% | {'✅' if cite >= 90 else '❌'} |",
        f"| 할루시네이션 방어(거부율) | {halluc:.1f}% | 90% | {'✅' if halluc >= 90 else '❌'} |",
        "",
    ]

    # 지표별 평균 점수(1~5)
    lines += ["## 지표별 평균 점수 (1~5, Foundry judge)", "| 지표 | 평균 | 통과율 |", "|---|---|---|"]
    for m in METRICS:
        vals = [r.metrics[m] for r in rows if m in r.metrics]
        flags = [r.passed[m] for r in rows if m in r.passed]
        if vals:
            lines.append(f"| {m} | {_avg(vals):.2f} | {_rate(flags):.1f}% |")
    lines.append("")

    # 유형별
    lines += ["## 유형별 결과", "| 유형 | 문항수 | groundedness 통과 | 인용율 |", "|---|---|---|---|"]
    for qtype in ["단일검색", "표데이터", "다년도", "다중문서교차", "종합요약", "원문부재"]:
        sub = [r for r in rows if r.qtype == qtype]
        if not sub:
            continue
        gf = [r.passed.get("groundedness", False) for r in sub if r.qtype != "원문부재"]
        cf = [r.cited for r in sub if r.qtype != "원문부재"]
        g = f"{_rate(gf):.0f}%" if gf else "-"
        c = f"{_rate(cf):.0f}%" if cf else "-"
        lines.append(f"| {qtype} | {len(sub)} | {g} | {c} |")
    lines.append("")
    return "\n".join(lines)
