from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent.tools import RetrievedSource
from eval import live
from eval.live import (
    CORE_METRICS,
    LiveEvaluationResult,
    evaluate_existing_answer,
    find_reference_answer,
    format_live_evaluation,
)


def _source(snippet: str = "검색 문장") -> RetrievedSource:
    return RetrievedSource(
        n=1,
        index="narrative-index",
        section_path="section/1",
        page_physical=1,
        chunk_type="text",
        snippet=snippet,
        score=0.9,
    )


def _evaluators(calls: dict[str, dict[str, Any]]) -> dict[str, object]:
    class FakeEvaluator:
        def __init__(self, metric: str):
            self.metric = metric

        def __call__(self, **kwargs: Any) -> dict[str, object]:
            calls[self.metric] = kwargs
            return {
                self.metric: 4.0,
                f"{self.metric}_passed": True,
                f"{self.metric}_reason": f"{self.metric} 판정 근거",
            }

    return {
        metric: FakeEvaluator(metric)
        for metric in (
            "groundedness",
            "relevance",
            "similarity",
            "coherence",
            "fluency",
        )
    }


def _result(*, ground_truth: str | None = None) -> LiveEvaluationResult:
    metric_names = ["groundedness", "relevance"]
    if ground_truth is not None:
        metric_names.append("similarity")
    metric_names.extend(["coherence", "fluency"])
    return LiveEvaluationResult(
        question="질문",
        answer="기존 답변",
        context="검색 문장",
        ground_truth=ground_truth,
        metrics={metric: 4.0 for metric in metric_names},
        passed={metric: True for metric in metric_names},
        reasons={metric: f"{metric} 판정 근거" for metric in metric_names},
    )


def test_evaluate_existing_answer_runs_four_metrics_without_reference(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: dict[str, dict[str, Any]] = {}
    sleeps: list[float] = []
    monkeypatch.setattr(live.time, "sleep", sleeps.append)

    result = evaluate_existing_answer(
        question="질문",
        answer="기존 답변",
        sources=[_source()],
        evidence=["구조화 근거"],
        evaluators=_evaluators(calls),
    )

    assert set(result.metrics) == set(CORE_METRICS)
    assert "similarity" not in calls
    assert calls["groundedness"] == {
        "query": "질문",
        "context": "구조화 근거\n\n검색 문장",
        "response": "기존 답변",
    }
    assert calls["relevance"] == {"query": "질문", "response": "기존 답변"}
    assert calls["coherence"] == {"query": "질문", "response": "기존 답변"}
    assert calls["fluency"] == {"response": "기존 답변"}
    assert sleeps == [1.0, 1.0, 1.0]
    assert "ask" not in vars(live)


def test_evaluate_existing_answer_adds_similarity_only_with_reference(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(live.time, "sleep", lambda _: None)

    result = evaluate_existing_answer(
        question="질문",
        answer="기존 답변",
        sources=[_source()],
        ground_truth="검토 정답",
        evaluators=_evaluators(calls),
    )

    assert list(result.metrics) == [
        "groundedness",
        "relevance",
        "similarity",
        "coherence",
        "fluency",
    ]
    assert calls["similarity"] == {
        "query": "질문",
        "response": "기존 답변",
        "ground_truth": "검토 정답",
    }


def test_live_result_rejects_incomplete_or_inconsistent_metric_contract():
    values = _result().model_dump()
    values["metrics"].pop("fluency")
    with pytest.raises(ValidationError, match="exactly the expected metrics"):
        LiveEvaluationResult.model_validate(values)

    values = _result().model_dump()
    values["passed"]["groundedness"] = False
    with pytest.raises(ValidationError, match="threshold 3"):
        LiveEvaluationResult.model_validate(values)

    values = _result(ground_truth="검토 정답").model_dump()
    values["reasons"].pop("similarity")
    with pytest.raises(ValidationError, match="exactly the expected metrics"):
        LiveEvaluationResult.model_validate(values)


def test_find_reference_answer_uses_stripped_exact_case_sensitive_match(
    tmp_path: Path,
):
    snapshot_path = tmp_path / "evaluation-data.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "question": "2025년 최종등급은?",
                        "ground_truth": "우수",
                    },
                    {"question": "정답 없는 질문", "ground_truth": "  "},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert find_reference_answer("  2025년 최종등급은?  ", snapshot_path) == "우수"
    assert find_reference_answer("2025년 최종등급은", snapshot_path) is None
    assert find_reference_answer("2025년 최종등급은? ".lower(), snapshot_path) == "우수"
    assert find_reference_answer("정답 없는 질문", snapshot_path) is None


def test_find_reference_answer_does_not_case_fold(tmp_path: Path):
    snapshot_path = tmp_path / "evaluation-data.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "rows": [
                    {"question": "Fund ABC grade?", "ground_truth": "Excellent"}
                ]
            }
        ),
        encoding="utf-8",
    )

    assert find_reference_answer("fund abc grade?", snapshot_path) is None


def test_format_live_evaluation_shows_similarity_na_without_reference():
    markdown = format_live_evaluation(_result())

    assert "# 답변 평가" in markdown
    assert "4/4" in markdown
    assert "| Similarity | N/A | N/A |" in markdown
    assert "일치하는 고객 검토 정답 없음" in markdown
    assert "## Evaluator 판정 근거" in markdown


def test_format_live_evaluation_includes_customer_reference_and_five_scores():
    markdown = format_live_evaluation(_result(ground_truth="검토 정답"))

    assert "5/5" in markdown
    assert "## 고객 검토 정답" in markdown
    assert "검토 정답" in markdown
    assert "| Similarity | 4.00 | PASS |" in markdown