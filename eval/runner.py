from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from pathlib import Path

from azure.identity import DefaultAzureCredential
from openai import RateLimitError
from azure.ai.evaluation import (
    AzureOpenAIModelConfiguration,
    CoherenceEvaluator,
    FluencyEvaluator,
    GroundednessEvaluator,
    RelevanceEvaluator,
    SimilarityEvaluator,
)

from agent.orchestrator import ask
from config.settings import get_settings
from eval.golden import GoldenItem
from eval.report import EvalRow

_NEGATION = [
    "없습니다",
    "없음",
    "않습니다",
    "않았습니다",
    "확인할 수 없",
    "확인되지 않",
    "제공되지 않",
    "포함되어 있지 않",
    "나와 있지 않",
    "찾을 수 없",
]


class MultilingualFluencyEvaluator(FluencyEvaluator):
    _PROMPTY_FILE = str(
        Path(__file__).with_name("fluency_multilingual.prompty").resolve()
    )


def _judge():
    s = get_settings()
    base = s.foundry_project_endpoint.split("/api/projects")[0]
    mc = AzureOpenAIModelConfiguration(
        azure_endpoint=base,
        azure_deployment=s.foundry_eval_deployment,
        api_version=s.foundry_api_version,
    )
    cred = DefaultAzureCredential()
    return mc, cred


def _build_evaluators() -> dict[str, object]:
    model_config, credential = _judge()
    kwargs = {
        "model_config": model_config,
        "threshold": 3,
        "credential": credential,
    }
    return {
        "groundedness": GroundednessEvaluator(**kwargs),
        "relevance": RelevanceEvaluator(**kwargs),
        "similarity": SimilarityEvaluator(**kwargs),
        "coherence": CoherenceEvaluator(**kwargs),
        "fluency": MultilingualFluencyEvaluator(**kwargs),
    }


def _score(result: dict, metric: str) -> tuple[float, bool, str]:
    value = result.get(metric)
    if value is None:
        value = result.get(f"{metric}_score")
    if value is None:
        raise ValueError(f"{metric} judge result is missing a score")
    try:
        score = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{metric} judge score is not numeric: {value!r}") from error
    if not math.isfinite(score) or not 1.0 <= score <= 5.0:
        raise ValueError(f"{metric} judge score must be finite and within 1..5: {score!r}")

    status = result.get(f"{metric}_status")
    if status is not None and str(status).casefold() != "completed":
        raise ValueError(f"{metric} judge status is not completed: {status!r}")

    binary_result = result.get(f"{metric}_result")
    if binary_result is not None and str(binary_result).casefold() not in {"pass", "fail"}:
        raise ValueError(f"{metric} judge result is not pass/fail: {binary_result!r}")

    passed_key = f"{metric}_passed"
    if passed_key in result:
        if not isinstance(result[passed_key], bool):
            raise ValueError(f"{metric} judge passed value is not boolean")
        passed = result[passed_key]
    else:
        if binary_result is None:
            raise ValueError(f"{metric} judge result is missing pass/fail")
        passed = str(binary_result).casefold() == "pass"
    if passed != (score >= 3.0):
        raise ValueError(
            f"{metric} judge pass value is inconsistent with threshold 3"
        )

    reason = str(result.get(f"{metric}_reason") or "").strip()
    if not reason:
        raise ValueError(f"{metric} judge result is missing a reason")
    return score, passed, reason


def _judge_result_summary(result: dict, metric: str) -> str:
    score = result.get(metric)
    if score is None:
        score = result.get(f"{metric}_score")

    def _bounded(value: object) -> str:
        rendered = repr(value)
        return rendered if len(rendered) <= 500 else f"{rendered[:497]}..."

    keys = ", ".join(sorted(str(key) for key in result))
    return "; ".join(
        [
            f"keys=[{keys}]",
            f"score={_bounded(score)}",
            f"status={_bounded(result.get(f'{metric}_status'))}",
            f"result={_bounded(result.get(f'{metric}_result'))}",
            f"passed={_bounded(result.get(f'{metric}_passed'))}",
            f"reason={_bounded(result.get(f'{metric}_reason'))}",
        ]
    )


def _is_rate_limit_error(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, RateLimitError):
            return True
        response = getattr(current, "response", None)
        status_code = getattr(current, "status_code", None) or getattr(
            response, "status_code", None
        )
        if status_code == 429:
            return True
        current = current.__cause__ or current.__context__
    return False


def _call_with_retry(evaluator, kwargs: dict, retries: int = 5) -> dict:
    """Call a Foundry judge evaluator, backing off on rate limits (429)."""
    delay = 10.0
    for attempt in range(retries):
        try:
            return evaluator(**kwargs)
        except Exception as error:
            if not _is_rate_limit_error(error):
                raise
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    return {}


def _evaluate_metric(
    evaluator,
    kwargs: dict,
    metric: str,
    result_retries: int = 3,
) -> tuple[float, bool, str]:
    if result_retries < 1:
        raise ValueError("result_retries must be at least 1")

    for attempt in range(result_retries):
        result = _call_with_retry(evaluator, kwargs)
        try:
            return _score(result, metric)
        except ValueError as error:
            if attempt == result_retries - 1:
                raise ValueError(
                    f"{metric} judge returned invalid results after "
                    f"{result_retries} attempts; last_error={error}; "
                    f"last_result=({_judge_result_summary(result, metric)})"
                ) from error
            time.sleep(1.0)

    raise AssertionError("unreachable")


def _require_ground_truth(item: GoldenItem) -> None:
    if item.ground_truth is None or not item.ground_truth.strip():
        raise ValueError(f"Golden item {item.id} is missing nonblank ground_truth")


async def evaluate_item(
    item: GoldenItem,
    evaluators: dict[str, object] | None = None,
) -> EvalRow:
    _require_ground_truth(item)
    evaluators = evaluators if evaluators is not None else _build_evaluators()
    result = await ask(item.question)
    answer = result.answer
    context_parts = [*result.evidence, *(source.snippet for source in result.sources)]
    context = "\n\n".join(context_parts) or "(검색 결과 없음)"

    evaluator_kwargs = {
        "groundedness": dict(query=item.question, context=context, response=answer),
        "relevance": dict(query=item.question, response=answer),
        "similarity": dict(
            query=item.question,
            response=answer,
            ground_truth=item.ground_truth,
        ),
        "coherence": dict(query=item.question, response=answer),
        "fluency": dict(response=answer),
    }
    metrics: dict[str, float] = {}
    passed: dict[str, bool] = {}
    reasons: dict[str, str] = {}
    for name, evaluator in evaluators.items():
        try:
            score, ok, reason = _evaluate_metric(
                evaluator,
                evaluator_kwargs[name],
                name,
            )
        except ValueError as error:
            raise ValueError(
                f"Evaluation failed for item={item.id!r}, metric={name!r}: {error}"
            ) from error
        metrics[name] = score
        passed[name] = ok
        reasons[name] = reason
        time.sleep(1.0)  # space out judge calls to respect TPM limits

    return EvalRow(
        id=item.id,
        qtype=item.qtype,
        question=item.question,
        answer=answer,
        ground_truth=item.ground_truth,
        context=context,
        metrics=metrics,
        passed=passed,
        reasons=reasons,
        steps=result.steps,
        sources=result.sources,
        cited=("[출처" in answer),
        refused=any(marker in answer for marker in _NEGATION)
        if item.qtype == "원문부재"
        else None,
    )


async def run_eval(
    items: list[GoldenItem],
    *,
    on_row: Callable[[EvalRow], None] | None = None,
) -> list[EvalRow]:
    for item in items:
        _require_ground_truth(item)
    evaluators = _build_evaluators()
    rows: list[EvalRow] = []
    for item in items:
        row = await evaluate_item(item, evaluators)
        rows.append(row)
        if on_row is not None:
            on_row(row)
    return rows


def run_eval_sync(
    items: list[GoldenItem],
    *,
    on_row: Callable[[EvalRow], None] | None = None,
) -> list[EvalRow]:
    return asyncio.run(run_eval(items, on_row=on_row))
