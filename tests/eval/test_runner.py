from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from agent.orchestrator import AnswerResult
from agent.tools import RetrievedSource, TraceStep
from eval import runner
from eval.golden import GoldenItem
from eval.report import EvalRow

METRIC_NAMES = (
    "groundedness",
    "relevance",
    "similarity",
    "coherence",
    "fluency",
)


def _answer_result(
    question: str,
    *,
    answer: str | None = None,
    snippets: tuple[str, ...] = ("first context", "second context"),
    evidence: tuple[str, ...] = (),
) -> AnswerResult:
    sources = [
        RetrievedSource(
            n=index,
            index="narrative-index",
            section_path=f"section/{index}",
            page_physical=index,
            chunk_type="text",
            snippet=snippet,
            score=1.0 / index,
        )
        for index, snippet in enumerate(snippets, start=1)
    ]
    return AnswerResult(
        answer=answer or f"[출처 1] answer for {question}",
        steps=[TraceStep(tool="search_narrative", query=question, n_hits=len(sources))],
        sources=sources,
        evidence=list(evidence),
    )


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    answers: dict[str, AnswerResult] | None = None,
    evaluator_results: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model_config = object()
    credential = object()
    state: dict[str, Any] = {
        "model_config": model_config,
        "credential": credential,
        "judge_calls": 0,
        "ask_calls": [],
        "constructor_calls": [],
        "evaluator_calls": [],
        "events": [],
        "sleeps": [],
    }

    def fake_judge() -> tuple[object, object]:
        state["judge_calls"] += 1
        return model_config, credential

    async def fake_ask(question: str) -> AnswerResult:
        state["ask_calls"].append(question)
        state["events"].append(("ask", question))
        if answers is not None and question in answers:
            return answers[question]
        return _answer_result(question)

    class FakeEvaluator:
        def __init__(self, metric: str):
            self.metric = metric

        def __call__(self, **kwargs: Any) -> dict[str, Any]:
            state["evaluator_calls"].append((self.metric, kwargs))
            item_marker = kwargs.get("query", kwargs.get("response"))
            state["events"].append((self.metric, item_marker))
            if evaluator_results is not None and self.metric in evaluator_results:
                return evaluator_results[self.metric]
            return {
                self.metric: 4.0,
                f"{self.metric}_passed": True,
                f"{self.metric}_reason": f"{self.metric} reason",
            }

    def evaluator_class(metric: str):
        def constructor(**kwargs: Any) -> FakeEvaluator:
            state["constructor_calls"].append((metric, kwargs))
            return FakeEvaluator(metric)

        return constructor

    monkeypatch.setattr(runner, "_judge", fake_judge)
    monkeypatch.setattr(runner, "ask", fake_ask)
    monkeypatch.setattr(runner.time, "sleep", state["sleeps"].append)
    monkeypatch.setattr(runner, "GroundednessEvaluator", evaluator_class("groundedness"))
    monkeypatch.setattr(runner, "RelevanceEvaluator", evaluator_class("relevance"))
    monkeypatch.setattr(runner, "SimilarityEvaluator", evaluator_class("similarity"), raising=False)
    monkeypatch.setattr(runner, "CoherenceEvaluator", evaluator_class("coherence"))
    monkeypatch.setattr(
        runner,
        "MultilingualFluencyEvaluator",
        evaluator_class("fluency"),
    )
    return state


def _item(item_id: str, *, qtype: str = "단일검색", ground_truth: str | None = None) -> GoldenItem:
    return GoldenItem(
        id=item_id,
        question=f"question {item_id}",
        qtype=qtype,
        ground_truth=ground_truth if ground_truth is not None else f"reviewed answer {item_id}",
    )


def test_run_eval_builds_exact_five_evaluators_once_per_run(monkeypatch: pytest.MonkeyPatch):
    state = _install_fakes(monkeypatch)

    rows = runner.run_eval_sync([_item("q1"), _item("q2")])

    assert len(rows) == 2
    assert state["judge_calls"] == 1
    assert [name for name, _ in state["constructor_calls"]] == list(METRIC_NAMES)
    for _, kwargs in state["constructor_calls"]:
        assert kwargs["model_config"] is state["model_config"]
        assert kwargs["credential"] is state["credential"]
        assert kwargs["threshold"] == 3
    for row in rows:
        assert set(row.metrics) == set(METRIC_NAMES)
        assert "retrieval" not in row.metrics


def test_multilingual_fluency_evaluator_uses_repo_prompt():
    prompt_path = Path(runner.MultilingualFluencyEvaluator._PROMPTY_FILE)

    assert prompt_path == Path(runner.__file__).with_name(
        "fluency_multilingual.prompty"
    ).resolve()
    prompt = prompt_path.read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())
    assert "Evaluate the response in the language in which it is written" in normalized_prompt
    assert "A non-English response is never a reason to skip" in normalized_prompt


def test_run_eval_requires_explicit_items():
    with pytest.raises(TypeError):
        runner.run_eval_sync()


def test_run_eval_passes_metric_specific_kwargs(monkeypatch: pytest.MonkeyPatch):
    item = _item("kwargs")
    answer_result = _answer_result(item.question)
    state = _install_fakes(monkeypatch, answers={item.question: answer_result})

    runner.run_eval_sync([item])

    calls = {name: kwargs for name, kwargs in state["evaluator_calls"]}
    context = "first context\n\nsecond context"
    assert calls == {
        "groundedness": {
            "query": item.question,
            "context": context,
            "response": answer_result.answer,
        },
        "relevance": {"query": item.question, "response": answer_result.answer},
        "similarity": {
            "query": item.question,
            "response": answer_result.answer,
            "ground_truth": item.ground_truth,
        },
        "coherence": {"query": item.question, "response": answer_result.answer},
        "fluency": {"response": answer_result.answer},
    }


def test_run_eval_includes_structured_evidence_in_groundedness_context(
    monkeypatch: pytest.MonkeyPatch,
):
    item = _item("structured-context")
    answer_result = _answer_result(
        item.question,
        snippets=("raw source row",),
        evidence=("2025년 공무원연금기금 종합등급: 우수",),
    )
    state = _install_fakes(monkeypatch, answers={item.question: answer_result})

    row = runner.run_eval_sync([item])[0]

    expected = "2025년 공무원연금기금 종합등급: 우수\n\nraw source row"
    groundedness_call = next(
        kwargs
        for metric, kwargs in state["evaluator_calls"]
        if metric == "groundedness"
    )
    assert row.context == expected
    assert groundedness_call["context"] == expected


def test_run_eval_extracts_sdk_results_and_preserves_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
):
    item = _item("absent", qtype="원문부재")
    answer_result = _answer_result(
        item.question,
        answer="제공된 자료에서 확인할 수 없습니다 [출처 1]",
    )
    evaluator_results = {
        "groundedness": {
            "groundedness": 5,
            "groundedness_passed": True,
            "groundedness_reason": "groundedness reason",
        },
        "relevance": {
            "relevance_score": 4,
            "relevance_result": "pass",
            "relevance_reason": "relevance reason",
        },
        "similarity": {
            "similarity": 2,
            "similarity_result": "fail",
            "similarity_reason": "similarity reason",
        },
        "coherence": {
            "coherence_score": 3,
            "coherence_passed": True,
            "coherence_reason": "coherence reason",
        },
        "fluency": {
            "fluency": 4,
            "fluency_result": "pass",
            "fluency_reason": "fluency reason",
        },
    }
    _install_fakes(
        monkeypatch,
        answers={item.question: answer_result},
        evaluator_results=evaluator_results,
    )

    row = runner.run_eval_sync([item])[0]

    assert isinstance(row, EvalRow)
    assert row.answer == answer_result.answer
    assert row.ground_truth == item.ground_truth
    assert row.context == "first context\n\nsecond context"
    assert row.metrics == {
        "groundedness": 5.0,
        "relevance": 4.0,
        "similarity": 2.0,
        "coherence": 3.0,
        "fluency": 4.0,
    }
    assert row.passed == {
        "groundedness": True,
        "relevance": True,
        "similarity": False,
        "coherence": True,
        "fluency": True,
    }
    assert row.reasons == {
        metric: f"{metric} reason" for metric in METRIC_NAMES
    }
    assert row.steps == answer_result.steps
    assert row.sources == answer_result.sources
    assert row.cited is True
    assert row.refused is True


def test_run_eval_uses_explicit_context_when_search_returns_no_sources(
    monkeypatch: pytest.MonkeyPatch,
):
    item = _item("no-sources")
    answer_result = _answer_result(item.question, snippets=())
    state = _install_fakes(monkeypatch, answers={item.question: answer_result})

    row = runner.run_eval_sync([item])[0]

    groundedness_call = next(
        kwargs
        for metric, kwargs in state["evaluator_calls"]
        if metric == "groundedness"
    )
    assert row.context == "(검색 결과 없음)"
    assert groundedness_call["context"] == row.context


@pytest.mark.parametrize("ground_truth", [None, "", "  \t"])
def test_run_eval_rejects_missing_ground_truth_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    ground_truth: str | None,
):
    state = _install_fakes(monkeypatch)
    item = GoldenItem(
        id="missing-ground-truth",
        question="question",
        qtype="단일검색",
        ground_truth=ground_truth,
    )

    with pytest.raises(ValueError, match="missing-ground-truth"):
        runner.run_eval_sync([item])

    assert state["evaluator_calls"] == []


def test_run_eval_processes_items_sequentially(monkeypatch: pytest.MonkeyPatch):
    first = _item("first")
    second = _item("second")
    answers = {
        first.question: _answer_result(first.question, answer="answer first"),
        second.question: _answer_result(second.question, answer="answer second"),
    }
    state = _install_fakes(monkeypatch, answers=answers)

    runner.run_eval_sync([first, second])

    assert state["events"] == [
        ("ask", first.question),
        ("groundedness", first.question),
        ("relevance", first.question),
        ("similarity", first.question),
        ("coherence", first.question),
        ("fluency", "answer first"),
        ("ask", second.question),
        ("groundedness", second.question),
        ("relevance", second.question),
        ("similarity", second.question),
        ("coherence", second.question),
        ("fluency", "answer second"),
    ]


def test_run_eval_emits_each_completed_row(monkeypatch: pytest.MonkeyPatch):
    items = [_item("first"), _item("second")]
    _install_fakes(monkeypatch)
    completed: list[EvalRow] = []

    rows = runner.run_eval_sync(items, on_row=completed.append)

    assert [row.id for row in rows] == ["first", "second"]
    assert [row.id for row in completed] == ["first", "second"]
    assert completed[0] is rows[0]
    assert completed[1] is rows[1]


def test_call_with_retry_keeps_exponential_429_backoff(monkeypatch: pytest.MonkeyPatch):
    class FakeRateLimitError(Exception):
        pass

    attempts = 0
    sleeps: list[float] = []

    def evaluator(**kwargs: str) -> dict[str, str]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise FakeRateLimitError
        return kwargs

    monkeypatch.setattr(runner, "RateLimitError", FakeRateLimitError)
    monkeypatch.setattr(runner.time, "sleep", sleeps.append)

    result = runner._call_with_retry(evaluator, {"response": "answer"})

    assert result == {"response": "answer"}
    assert attempts == 3
    assert sleeps == [10.0, 20.0]


def test_call_with_retry_handles_sdk_wrapper_with_rate_limit_cause(
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeRateLimitError(Exception):
        pass

    attempts = 0
    sleeps: list[float] = []

    def evaluator(**kwargs: str) -> dict[str, str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            try:
                raise FakeRateLimitError("429")
            except FakeRateLimitError as error:
                raise RuntimeError("SDK wrapped OpenAI failure") from error
        return kwargs

    monkeypatch.setattr(runner, "RateLimitError", FakeRateLimitError)
    monkeypatch.setattr(runner.time, "sleep", sleeps.append)

    result = runner._call_with_retry(evaluator, {"response": "answer"})

    assert result == {"response": "answer"}
    assert attempts == 2
    assert sleeps == [10.0]


def test_call_with_retry_does_not_retry_unrelated_errors(
    monkeypatch: pytest.MonkeyPatch,
):
    attempts = 0
    sleeps: list[float] = []

    def evaluator(**kwargs: str) -> dict[str, str]:
        nonlocal attempts
        attempts += 1
        raise ValueError("invalid evaluator input")

    monkeypatch.setattr(runner.time, "sleep", sleeps.append)

    with pytest.raises(ValueError, match="invalid evaluator input"):
        runner._call_with_retry(evaluator, {"response": "answer"})

    assert attempts == 1
    assert sleeps == []


def test_evaluate_metric_retries_skipped_nonempty_response(
    monkeypatch: pytest.MonkeyPatch,
):
    attempts = 0
    sleeps: list[float] = []

    def evaluator(**kwargs: str) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {
                "fluency": None,
                "fluency_passed": None,
                "fluency_result": "not_applicable",
                "fluency_reason": "Not applicable: Korean response",
                "fluency_status": "skipped",
            }
        return {
            "fluency": 4,
            "fluency_passed": True,
            "fluency_result": "pass",
            "fluency_reason": "Korean response is fluent.",
            "fluency_status": "completed",
        }

    monkeypatch.setattr(runner.time, "sleep", sleeps.append)

    result = runner._evaluate_metric(
        evaluator,
        {"response": "한국어 답변"},
        "fluency",
        result_retries=2,
    )

    assert result == (4.0, True, "Korean response is fluent.")
    assert attempts == 2
    assert sleeps == [1.0]


def test_evaluate_metric_raises_after_repeated_invalid_results(
    monkeypatch: pytest.MonkeyPatch,
):
    attempts = 0

    def evaluator(**kwargs: str) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        return {
            "fluency": None,
            "fluency_passed": None,
            "fluency_result": "not_applicable",
            "fluency_reason": "Not applicable: Korean response",
            "fluency_status": "skipped",
        }

    monkeypatch.setattr(runner.time, "sleep", lambda _: None)

    with pytest.raises(ValueError, match="after 2 attempts"):
        runner._evaluate_metric(
            evaluator,
            {"response": "한국어 답변"},
            "fluency",
            result_retries=2,
        )

    assert attempts == 2


def test_evaluate_metric_reports_sanitized_last_invalid_result(
    monkeypatch: pytest.MonkeyPatch,
):
    result = {
        "groundedness": None,
        "groundedness_score": None,
        "groundedness_passed": None,
        "groundedness_result": "not_applicable",
        "groundedness_reason": "Judge output could not be parsed.",
        "groundedness_status": "skipped",
        "groundedness_properties": {
            "sample_input": "secret prompt payload",
            "sample_output": "large raw model output",
        },
    }

    monkeypatch.setattr(runner.time, "sleep", lambda _: None)

    with pytest.raises(ValueError) as error:
        runner._evaluate_metric(
            lambda **kwargs: result,
            {"response": "answer"},
            "groundedness",
            result_retries=2,
        )

    message = str(error.value)
    assert "groundedness" in message
    assert "score=None" in message
    assert "status='skipped'" in message
    assert "result='not_applicable'" in message
    assert "passed=None" in message
    assert "reason='Judge output could not be parsed.'" in message
    assert "groundedness_properties" in message
    assert "secret prompt payload" not in message
    assert "large raw model output" not in message


def test_run_eval_identifies_item_when_judge_results_remain_invalid(
    monkeypatch: pytest.MonkeyPatch,
):
    item = _item("q9")
    _install_fakes(
        monkeypatch,
        evaluator_results={
            "groundedness": {
                "groundedness": None,
                "groundedness_passed": None,
                "groundedness_result": "not_applicable",
                "groundedness_reason": "Judge output could not be parsed.",
                "groundedness_status": "skipped",
            }
        },
    )

    with pytest.raises(ValueError) as error:
        runner.run_eval_sync([item])

    message = str(error.value)
    assert "item='q9'" in message
    assert "metric='groundedness'" in message


@pytest.mark.parametrize(
    "result",
    [
        {"groundedness_passed": False, "groundedness_reason": "missing score"},
        {
            "groundedness": math.nan,
            "groundedness_passed": False,
            "groundedness_reason": "not applicable",
        },
        {
            "groundedness": 6,
            "groundedness_passed": True,
            "groundedness_reason": "out of range",
        },
        {
            "groundedness": 4,
            "groundedness_result": "unknown",
            "groundedness_reason": "unknown result",
        },
        {
            "groundedness": 4,
            "groundedness_result": "pass",
        },
        {
            "groundedness": 4,
            "groundedness_passed": False,
            "groundedness_reason": "inconsistent threshold result",
        },
    ],
)
def test_score_rejects_invalid_judge_results(result: dict[str, Any]):
    with pytest.raises(ValueError, match="groundedness"):
        runner._score(result, "groundedness")