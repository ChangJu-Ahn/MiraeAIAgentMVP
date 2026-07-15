from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from eval.report import EvalRow


class FailureCluster(BaseModel):
    code: str
    title: str
    item_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    recommendation: str
    priority: int


_CLUSTER_SPECS = (
    (
        "evidence-context",
        "근거 부족 또는 context truncation 후보",
        ("groundedness",),
        "검색 근거와 judge context를 함께 검토하고 source snippet 절단 여부를 확인합니다.",
        1,
    ),
    (
        "intent-routing",
        "의도 분류 또는 routing 후보",
        ("relevance",),
        "질문 의도 분류와 검색 도구 routing이 질문 범위에 맞는지 검토합니다.",
        2,
    ),
    (
        "ground-truth-key-points",
        "검토 정답 핵심 포인트 누락 후보",
        ("similarity",),
        "답변과 검토 정답을 대조해 누락된 핵심 포인트를 검색 및 합성 단계에 반영합니다.",
        3,
    ),
    (
        "synthesis-expression",
        "답변 합성 또는 표현 후보",
        ("coherence", "fluency"),
        "근거를 유지하면서 답변 구조와 문장 표현을 개선합니다.",
        4,
    ),
)

_GLOBAL_SCOPE_TERMS = ("상위", "하위", "순위", "전체", "가장")
_GLOBAL_RECOMMENDATION = (
    "전체 top-k를 일괄 확대하지 않습니다. 일반 사실 질문은 top-5를 유지하고, "
    "cross-section 비교는 TOC/metadata fan-out을 사용하며, 전역 집계와 순위는 "
    "정규화 레코드와 numeric aggregation tool로 처리합니다."
)


def _failed(row: EvalRow, metric: str, threshold: float = 3.0) -> bool:
    if metric in row.passed:
        return row.passed[metric] is False
    score = row.metrics.get(metric)
    return score is not None and score < threshold


def analyze_rows(rows: Sequence[EvalRow]) -> list[FailureCluster]:
    failed_by_code: dict[str, dict[str, set[str]]] = {
        code: {} for code, *_ in _CLUSTER_SPECS
    }
    for row in rows:
        for code, _, metrics, _, _ in _CLUSTER_SPECS:
            failed_metrics = {metric for metric in metrics if _failed(row, metric)}
            if failed_metrics:
                failed_by_code[code].setdefault(row.id, set()).update(failed_metrics)

    clusters: list[FailureCluster] = []
    for code, title, _, recommendation, priority in _CLUSTER_SPECS:
        failures = failed_by_code[code]
        item_ids = sorted(failures)
        if not item_ids:
            continue
        clusters.append(
            FailureCluster(
                code=code,
                title=title,
                item_ids=item_ids,
                evidence=[
                    f"{item_id}: failed {', '.join(sorted(failures[item_id]))}"
                    for item_id in item_ids
                ],
                recommendation=recommendation,
                priority=priority,
            )
        )

    coverage: dict[str, dict[str, object]] = {}
    for row in rows:
        if not any(term in row.question for term in _GLOBAL_SCOPE_TERMS):
            continue
        if not row.steps or not all(step.n_hits <= 5 for step in row.steps):
            continue
        detail = coverage.setdefault(
            row.id,
            {"max_hits": 0, "call_count": 0, "tools": set()},
        )
        detail["max_hits"] = max(int(detail["max_hits"]), *(step.n_hits for step in row.steps))
        detail["call_count"] = max(int(detail["call_count"]), len(row.steps))
        tools = detail["tools"]
        if isinstance(tools, set):
            tools.update(step.tool for step in row.steps)

    coverage_ids = sorted(coverage)
    if coverage_ids:
        evidence: list[str] = []
        for item_id in coverage_ids:
            detail = coverage[item_id]
            tools = ", ".join(sorted(str(tool) for tool in detail["tools"]))
            evidence.append(
                f"{item_id}: max n_hits={detail['max_hits']} across "
                f"{detail['call_count']} calls; tools={tools}"
            )
        clusters.append(
            FailureCluster(
                code="global-coverage",
                title="전역 범위 coverage 위험",
                item_ids=coverage_ids,
                evidence=evidence,
                recommendation=_GLOBAL_RECOMMENDATION,
                priority=2,
            )
        )

    return clusters