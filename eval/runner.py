from __future__ import annotations

import asyncio
import time

from azure.identity import DefaultAzureCredential
from openai import RateLimitError
from azure.ai.evaluation import (
    AzureOpenAIModelConfiguration,
    CoherenceEvaluator,
    FluencyEvaluator,
    GroundednessEvaluator,
    RelevanceEvaluator,
    RetrievalEvaluator,
)

from agent.orchestrator import ask
from config.settings import get_settings
from eval.golden import GOLDEN_QA, GoldenItem
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


def _score(result: dict, metric: str) -> tuple[float, bool]:
    val = result.get(metric)
    score = float(val) if val is not None else 0.0
    return score, bool(result.get(f"{metric}_passed", False))


def _call_with_retry(evaluator, kwargs: dict, retries: int = 5) -> dict:
    """Call a Foundry judge evaluator, backing off on rate limits (429)."""
    delay = 10.0
    for attempt in range(retries):
        try:
            return evaluator(**kwargs)
        except RateLimitError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    return {}


async def evaluate_item(item: GoldenItem) -> EvalRow:
    result = await ask(item.question)
    answer = result.answer
    context = "\n\n".join(s.snippet for s in result.sources) or "(검색 결과 없음)"

    if item.qtype == "원문부재":
        refused = any(m in answer for m in _NEGATION)
        return EvalRow(
            id=item.id,
            qtype=item.qtype,
            question=item.question,
            answer=answer,
            metrics={},
            passed={},
            cited=False,
            refused=refused,
        )

    mc, cred = _judge()
    evaluators = {
        "groundedness": (
            GroundednessEvaluator(model_config=mc, credential=cred),
            dict(query=item.question, context=context, response=answer),
        ),
        "relevance": (
            RelevanceEvaluator(model_config=mc, credential=cred),
            dict(query=item.question, response=answer),
        ),
        "retrieval": (
            RetrievalEvaluator(model_config=mc, credential=cred),
            dict(query=item.question, context=context),
        ),
        "coherence": (
            CoherenceEvaluator(model_config=mc, credential=cred),
            dict(query=item.question, response=answer),
        ),
        "fluency": (
            FluencyEvaluator(model_config=mc, credential=cred),
            dict(response=answer),
        ),
    }
    metrics: dict[str, float] = {}
    passed: dict[str, bool] = {}
    for name, (evaluator, kwargs) in evaluators.items():
        res = _call_with_retry(evaluator, kwargs)
        score, ok = _score(res, name)
        metrics[name] = score
        passed[name] = ok
        time.sleep(1.0)  # space out judge calls to respect TPM limits

    return EvalRow(
        id=item.id,
        qtype=item.qtype,
        question=item.question,
        answer=answer,
        metrics=metrics,
        passed=passed,
        cited=("[출처" in answer),
        refused=None,
    )


async def run_eval(items: list[GoldenItem] | None = None) -> list[EvalRow]:
    items = items if items is not None else GOLDEN_QA
    rows: list[EvalRow] = []
    for item in items:
        rows.append(await evaluate_item(item))
    return rows


def run_eval_sync(items: list[GoldenItem] | None = None) -> list[EvalRow]:
    return asyncio.run(run_eval(items))
