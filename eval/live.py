from __future__ import annotations

import json
import math
import re
import time
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from agent.tools import RetrievedSource
from eval.report import METRICS
from eval.runner import _build_evaluators, _evaluate_metric

CORE_METRICS = ("groundedness", "relevance", "coherence", "fluency")
PUBLIC_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1] / "public" / "evaluation-data.json"
)

_METRIC_LABELS = {
    "groundedness": "Groundedness",
    "relevance": "Relevance",
    "similarity": "Similarity",
    "coherence": "Coherence",
    "fluency": "Fluency",
}


class LiveEvaluationResult(BaseModel):
    question: str
    answer: str
    context: str
    ground_truth: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    passed: dict[str, bool] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_metric_contract(self) -> LiveEvaluationResult:
        expected = set(CORE_METRICS)
        if self.ground_truth is not None and self.ground_truth.strip():
            expected.add("similarity")

        for field_name in ("metrics", "passed", "reasons"):
            actual = set(getattr(self, field_name))
            if actual != expected:
                raise ValueError(
                    f"{field_name} must contain exactly the expected metrics: "
                    f"{', '.join(metric for metric in METRICS if metric in expected)}"
                )

        for metric, score in self.metrics.items():
            if not math.isfinite(score) or not 1.0 <= score <= 5.0:
                raise ValueError(f"{metric} score must be finite and within 1..5")
            if self.passed[metric] != (score >= 3.0):
                raise ValueError(
                    f"{metric} pass value is inconsistent with threshold 3"
                )
            if not self.reasons[metric].strip():
                raise ValueError(f"{metric} reason must be nonblank")
        return self


@lru_cache(maxsize=16)
def _reference_answers(snapshot_path: str) -> dict[str, str]:
    payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("public evaluation snapshot rows must be a list")

    answers: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("public evaluation snapshot rows must be objects")
        question = row.get("question")
        ground_truth = row.get("ground_truth")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("public evaluation question must be nonblank")
        if not isinstance(ground_truth, str) or not ground_truth.strip():
            continue
        normalized_question = question.strip()
        normalized_answer = ground_truth.strip()
        existing = answers.get(normalized_question)
        if existing is not None and existing != normalized_answer:
            raise ValueError(
                f"conflicting customer review answers for {normalized_question!r}"
            )
        answers[normalized_question] = normalized_answer
    return answers


def find_reference_answer(
    question: str,
    snapshot_path: Path | None = None,
) -> str | None:
    path = (snapshot_path or PUBLIC_SNAPSHOT_PATH).resolve()
    return _reference_answers(str(path)).get(question.strip())


def evaluate_existing_answer(
    question: str,
    answer: str,
    sources: list[RetrievedSource],
    evidence: list[str] | None = None,
    ground_truth: str | None = None,
    evaluators: dict[str, object] | None = None,
) -> LiveEvaluationResult:
    resolved_ground_truth = (
        ground_truth.strip()
        if ground_truth is not None and ground_truth.strip()
        else None
    )
    context_parts = [*(evidence or []), *(source.snippet for source in sources)]
    context = "\n\n".join(context_parts) or "(검색 결과 없음)"
    resolved_evaluators = evaluators if evaluators is not None else _build_evaluators()

    evaluator_kwargs: dict[str, dict[str, str]] = {
        "groundedness": {
            "query": question,
            "context": context,
            "response": answer,
        },
        "relevance": {"query": question, "response": answer},
        "coherence": {"query": question, "response": answer},
        "fluency": {"response": answer},
    }
    if resolved_ground_truth is not None:
        evaluator_kwargs["similarity"] = {
            "query": question,
            "response": answer,
            "ground_truth": resolved_ground_truth,
        }

    selected_metrics = [
        metric
        for metric in METRICS
        if metric != "similarity" or resolved_ground_truth is not None
    ]
    metrics: dict[str, float] = {}
    passed: dict[str, bool] = {}
    reasons: dict[str, str] = {}
    for index, metric in enumerate(selected_metrics):
        try:
            score, ok, reason = _evaluate_metric(
                resolved_evaluators[metric],
                evaluator_kwargs[metric],
                metric,
            )
        except ValueError as error:
            raise ValueError(f"Live evaluation failed for metric={metric!r}: {error}") from error
        metrics[metric] = score
        passed[metric] = ok
        reasons[metric] = reason
        if index < len(selected_metrics) - 1:
            time.sleep(1.0)

    return LiveEvaluationResult(
        question=question,
        answer=answer,
        context=context,
        ground_truth=resolved_ground_truth,
        metrics=metrics,
        passed=passed,
        reasons=reasons,
    )


def _code_block(value: str) -> list[str]:
    longest_run = max(
        (len(match.group(0)) for match in re.finditer(r"`+", value)),
        default=0,
    )
    fence = "`" * max(3, longest_run + 1)
    return [f"{fence}text", value, fence]


def format_live_evaluation(result: LiveEvaluationResult) -> str:
    metric_count = len(result.metrics)
    pass_count = sum(result.passed.values())
    lines = [
        "# 답변 평가",
        "",
        f"- 통과: **{pass_count}/{metric_count}**",
        "- 점수 범위: **1~5점**",
        "- 통과 기준: **3점 이상**",
        "",
        "## 질문",
        *_code_block(result.question),
        "",
        "## 평가 대상 답변",
        *_code_block(result.answer),
        "",
    ]
    if result.ground_truth is not None:
        lines += [
            "## 고객 검토 정답",
            *_code_block(result.ground_truth),
            "",
        ]

    lines += [
        "## 점수",
        "| Evaluator | 점수 | 판정 |",
        "|---|---:|---|",
    ]
    for metric in METRICS:
        label = _METRIC_LABELS[metric]
        if metric not in result.metrics:
            lines.append(f"| {label} | N/A | N/A |")
            continue
        status = "PASS" if result.passed[metric] else "FAIL"
        lines.append(f"| {label} | {result.metrics[metric]:.2f} | {status} |")

    lines += ["", "## Evaluator 판정 근거", ""]
    for metric in METRICS:
        label = _METRIC_LABELS[metric]
        lines.append(f"### {label}")
        if metric not in result.reasons:
            lines.append("N/A - 일치하는 고객 검토 정답 없음")
        else:
            lines.append(result.reasons[metric])
        lines.append("")
    return "\n".join(lines).rstrip()