from __future__ import annotations

import importlib

import pytest

from agent.tools import TraceStep
from eval.report import EvalRow


METRICS = ("groundedness", "relevance", "similarity", "coherence", "fluency")


def _row(
    item_id: str,
    *,
    failed: tuple[str, ...] = (),
    question: str = "일반 사실 질문",
    steps: list[TraceStep] | None = None,
) -> EvalRow:
    return EvalRow(
        id=item_id,
        qtype="미분류",
        question=question,
        answer="답변",
        ground_truth="검토 정답",
        context="judge context",
        metrics={metric: 2.0 if metric in failed else 4.0 for metric in METRICS},
        passed={metric: metric not in failed for metric in METRICS},
        reasons={metric: f"{metric} reason" for metric in METRICS},
        steps=steps or [],
    )


@pytest.mark.parametrize(
    ("metric", "expected_code"),
    [
        ("groundedness", "evidence-context"),
        ("relevance", "intent-routing"),
        ("similarity", "ground-truth-key-points"),
        ("coherence", "synthesis-expression"),
        ("fluency", "synthesis-expression"),
    ],
)
def test_analyze_rows_clusters_each_failed_metric(metric: str, expected_code: str):
    analysis = importlib.import_module("eval.analysis")

    clusters = analysis.analyze_rows([_row("q-failed", failed=(metric,))])

    cluster = next(cluster for cluster in clusters if cluster.code == expected_code)
    assert cluster.item_ids == ["q-failed"]
    assert any("q-failed" in evidence for evidence in cluster.evidence)
    assert cluster.recommendation
    assert cluster.priority > 0


def test_analyze_rows_detects_global_coverage_risk_with_bounded_calls():
    analysis = importlib.import_module("eval.analysis")
    row = _row(
        "q-global",
        question="전체 기금 중 가장 높은 상위 순위는?",
        steps=[
            TraceStep(tool="search_narrative", query="전체 기금", n_hits=5),
            TraceStep(tool="search_tables", query="점수 순위", n_hits=3),
        ],
    )

    clusters = analysis.analyze_rows([row])

    cluster = next(cluster for cluster in clusters if cluster.code == "global-coverage")
    assert cluster.item_ids == ["q-global"]
    evidence = " ".join(cluster.evidence)
    assert "q-global" in evidence
    assert "max n_hits=5" in evidence
    assert "2 calls" in evidence
    assert "search_narrative" in evidence
    assert "search_tables" in evidence
    assert "일반 사실 질문은 top-5를 유지" in cluster.recommendation
    assert "TOC/metadata fan-out" in cluster.recommendation
    assert "numeric aggregation tool" in cluster.recommendation
    assert "전체 top-k를 일괄 확대하지" in cluster.recommendation


@pytest.mark.parametrize(
    "row",
    [
        _row(
            "ordinary",
            question="평가 목적은 무엇인가요?",
            steps=[TraceStep(tool="search_narrative", query="목적", n_hits=5)],
        ),
        _row("no-steps", question="전체 순위를 알려주세요"),
        _row(
            "wide-call",
            question="상위 기금 순위를 알려주세요",
            steps=[
                TraceStep(tool="search_narrative", query="상위", n_hits=6),
                TraceStep(tool="search_tables", query="순위", n_hits=5),
            ],
        ),
    ],
    ids=["ordinary-question", "no-search-steps", "call-over-five"],
)
def test_analyze_rows_does_not_flag_non_risks(row: EvalRow):
    analysis = importlib.import_module("eval.analysis")

    clusters = analysis.analyze_rows([row])

    assert all(cluster.code != "global-coverage" for cluster in clusters)


def test_analyze_rows_has_stable_cluster_and_item_order_without_duplicates():
    analysis = importlib.import_module("eval.analysis")
    rows = [
        _row("q2", failed=("similarity", "fluency")),
        _row(
            "q1",
            failed=("groundedness", "relevance", "coherence"),
            question="전체 순위는?",
            steps=[TraceStep(tool="search_tables", query="순위", n_hits=5)],
        ),
        _row("q2", failed=("groundedness", "relevance", "similarity", "fluency")),
    ]

    clusters = analysis.analyze_rows(rows)
    reversed_clusters = analysis.analyze_rows(list(reversed(rows)))

    assert [cluster.code for cluster in clusters] == [
        "evidence-context",
        "intent-routing",
        "ground-truth-key-points",
        "synthesis-expression",
        "global-coverage",
    ]
    assert clusters == reversed_clusters
    for cluster in clusters:
        assert cluster.item_ids == sorted(set(cluster.item_ids))
