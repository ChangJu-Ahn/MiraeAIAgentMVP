# P5: Foundry Evaluation + Golden Q&A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Golden Q&A 평가셋(AI 초안, 6유형)에 대해 P3 에이전트를 실행하고, **Microsoft Foundry 평가 SDK(azure-ai-evaluation)**의 Foundry judge(키리스)로 Groundedness·Relevance·Retrieval·Coherence·Fluency를 측정하며, 인용 정확도·할루시네이션 방어를 함께 계산해 유형별·전체 점수와 목표선(정확도 80%·인용 90%·할루시네이션 방어 90%) 대비 리포트를 생성한다.

**Architecture:** `eval/golden.py`가 구조화된 Golden Q&A(유형 라벨 포함)를 제공한다. `eval/runner.py`가 각 질문에 P3 `ask()`를 실행해 (query, response, context)를 만들고, azure-ai-evaluation 평가자(Foundry judge, 키리스)로 지표를 계산하며, 원문부재 유형은 거부(refusal) 여부, 나머지는 인용 포함 여부를 추가로 판정한다. `eval/report.py`(순수 함수)가 결과를 유형별·전체로 집계해 마크다운 리포트로 변환한다. `eval/run_eval.py` CLI가 전체를 실행해 `reports/eval-report.md`를 쓴다. 순수 로직(데이터셋·집계·리포트)은 유닛 테스트, 평가자 호출은 소규모 실 통합 테스트.

**Tech Stack:** Python 3.12(uv), azure-ai-evaluation (GroundednessEvaluator, RelevanceEvaluator, RetrievalEvaluator, CoherenceEvaluator, FluencyEvaluator + AzureOpenAIModelConfiguration), azure-identity(DefaultAzureCredential), P3 agent.orchestrator.ask, pydantic, pytest.

## Global Constraints

- 답변 평가는 반드시 **Microsoft Foundry 평가**를 사용: azure-ai-evaluation 평가자를 **Foundry 모델(judge)**로 구동. (스펙 §1, 메모리)
- 키리스: judge 모델 구성은 `AzureOpenAIModelConfiguration(azure_endpoint=<foundry base>, azure_deployment=settings.foundry_chat_deployment, api_version=settings.foundry_api_version)` + 평가자에 `credential=DefaultAzureCredential()`. API 키 금지. (검증됨: 키리스 Groundedness 호출 성공)
- 지표: Groundedness, Relevance, Retrieval, Coherence, Fluency(Foundry judge) + Citation(결정적: 답변에 `[출처` 포함) + 할루시네이션 방어(원문부재 유형에서 거부). (스펙 §6, V6)
- 목표선: 정확도(groundedness 통과율) ≥ 80%, 인용 ≥ 90%, 할루시네이션 방어 ≥ 90%. (스펙 §6)
- Golden Q&A는 AI가 초안 작성(6유형: 단일검색·표데이터·다년도·다중문서교차·종합요약·원문부재). 사용자가 나중에 리뷰. (스펙 §6, 사용자 방침)
- 에이전트 호출은 P3 `agent.orchestrator.ask`만. 설정은 `config.settings`만.
- 실제 배포 리소스 사용, 실제 Azure 호출 테스트 허용.
- 리포트 산출물은 `reports/`(gitignore 아님 — 커밋). 원본 문서 `Docs/` 유지.
- 모든 커밋 끝에 트레일러:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## 확정된 azure-ai-evaluation API (검증됨, 키리스)
- `from azure.ai.evaluation import GroundednessEvaluator, RelevanceEvaluator, RetrievalEvaluator, CoherenceEvaluator, FluencyEvaluator, AzureOpenAIModelConfiguration`
- `AzureOpenAIModelConfiguration(azure_endpoint=..., azure_deployment=..., api_version=...)` (dict형; api_key 생략 → 키리스).
- `GroundednessEvaluator(model_config=mc, credential=DefaultAzureCredential())` → `evaluator(query=, context=, response=)` 반환 예: `{'groundedness': 5.0, 'groundedness_passed': True, 'groundedness_result': 'pass', 'groundedness_reason': ...}` (검증됨).
- **평가자별 필수 인자(실행 중 확인·조정)**: Groundedness=(query, context, response); Relevance=(query, response); Retrieval=(query, context); Coherence=(query, response); Fluency=(response). 설치 버전에서 각 evaluator를 1회 호출해 필요한 키를 확인하고, 다르면 최소 조정(결과 dict의 `<metric>` 점수와 `<metric>_passed` 키 사용).

---

## File Structure

- `eval/__init__.py`
- `eval/golden.py` — `GoldenItem`(id, question, qtype), `GOLDEN_QA: list[GoldenItem]` (AI 초안, 6유형)
- `eval/report.py` — `MetricSummary`/`EvalRow` 집계 + `build_report(rows) -> str`(마크다운) (순수)
- `eval/runner.py` — judge 구성, 평가자 실행, 행 생성 (`evaluate_item`, `run_eval`)
- `eval/run_eval.py` — CLI (전체 실행 → reports/eval-report.md)
- `tests/eval/__init__.py`
- `tests/eval/test_golden.py` — 데이터셋 구조 (순수)
- `tests/eval/test_report.py` — 집계/리포트 (순수, 합성 결과)
- `tests/eval/test_runner_smoke.py` — 소규모 실 통합(1~2문항)
- `README.md` (수정: 평가 실행법)

---

## Task 1: Golden Q&A 데이터셋 (eval/golden.py)

**Files:**
- Create: `eval/__init__.py`, `eval/golden.py`, `tests/eval/__init__.py`, `tests/eval/test_golden.py`

**Interfaces:**
- Produces:
  - `QType` 값: `"단일검색" | "표데이터" | "다년도" | "다중문서교차" | "종합요약" | "원문부재"`.
  - `GoldenItem(BaseModel)`: `id: str`, `question: str`, `qtype: str`.
  - `GOLDEN_QA: list[GoldenItem]` — 18개(각 유형 ≥ 2). 2025 자산운용부문 기금운용평가보고서 실제 내용 기반.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/eval/__init__.py` (empty), then `tests/eval/test_golden.py`:
```python
from eval.golden import GOLDEN_QA, GoldenItem

VALID_TYPES = {"단일검색", "표데이터", "다년도", "다중문서교차", "종합요약", "원문부재"}


def test_golden_qa_nonempty_and_typed():
    assert len(GOLDEN_QA) >= 12
    assert all(isinstance(x, GoldenItem) for x in GOLDEN_QA)
    assert all(x.qtype in VALID_TYPES for x in GOLDEN_QA)
    assert all(x.question.strip() for x in GOLDEN_QA)


def test_all_six_types_present():
    types = {x.qtype for x in GOLDEN_QA}
    assert VALID_TYPES.issubset(types), f"missing types: {VALID_TYPES - types}"


def test_ids_unique():
    ids = [x.id for x in GOLDEN_QA]
    assert len(ids) == len(set(ids))


def test_has_hallucination_probes():
    assert sum(1 for x in GOLDEN_QA if x.qtype == "원문부재") >= 2
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/eval/test_golden.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.golden'` (또는 'eval')

- [ ] **Step 3: golden 구현**

Create `eval/__init__.py` (empty). Create `eval/golden.py`:
```python
from __future__ import annotations

from pydantic import BaseModel


class GoldenItem(BaseModel):
    id: str
    question: str
    qtype: str


GOLDEN_QA: list[GoldenItem] = [
    # 단일검색
    GoldenItem(id="q01", question="자산운용부문 평가의 목적은 무엇인가요?", qtype="단일검색"),
    GoldenItem(id="q02", question="기금운용평가단은 어떻게 구성되나요?", qtype="단일검색"),
    GoldenItem(id="q03", question="자산운용 평가의 근거가 되는 법령은 무엇인가요?", qtype="단일검색"),
    # 표데이터
    GoldenItem(id="q04", question="기금운용평가 종합등급에는 어떤 등급들이 있나요?", qtype="표데이터"),
    GoldenItem(id="q05", question="탁월 등급과 우수 등급의 정의 차이는 무엇인가요?", qtype="표데이터"),
    GoldenItem(id="q06", question="대규모 기금의 계량평가 지표에는 어떤 것이 있나요?", qtype="표데이터"),
    # 다년도
    GoldenItem(id="q07", question="전기 평가결과 대비 평가 방식의 변화가 있었나요?", qtype="다년도"),
    GoldenItem(id="q08", question="평가 등급 구간은 몇 단계로 구분되나요?", qtype="다년도"),
    # 다중문서교차
    GoldenItem(id="q09", question="대형·중소형 기금과 대규모 기금의 평가 방법은 어떻게 다른가요?", qtype="다중문서교차"),
    GoldenItem(id="q10", question="혁신성장 분야 투자에 대한 가점은 어떻게 부여되나요?", qtype="다중문서교차"),
    # 종합요약
    GoldenItem(id="q11", question="2025회계연도 자산운용부문 평가의 특징을 요약해 주세요.", qtype="종합요약"),
    GoldenItem(id="q12", question="평가결과 공개 방식을 요약해 주세요.", qtype="종합요약"),
    # 원문부재 (할루시네이션 방어)
    GoldenItem(id="q13", question="이 보고서에 나온 2025년 애플 아이폰 판매량은 얼마인가요?", qtype="원문부재"),
    GoldenItem(id="q14", question="이 보고서에서 삼성전자 반도체 매출 전망치는 얼마로 나오나요?", qtype="원문부재"),
    GoldenItem(id="q15", question="보고서에 기재된 비트코인 목표가는 얼마인가요?", qtype="원문부재"),
    # 추가 단일/표
    GoldenItem(id="q16", question="단기자금 통합운용 제도 참여 기금에 대한 가점 기준은?", qtype="단일검색"),
    GoldenItem(id="q17", question="대형 기금과 중소형 기금은 어떤 기준으로 구분되나요?", qtype="표데이터"),
    GoldenItem(id="q18", question="비계량평가와 계량평가는 각각 무엇을 평가하나요?", qtype="다중문서교차"),
]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/eval/test_golden.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add eval/__init__.py eval/golden.py tests/eval/__init__.py tests/eval/test_golden.py
git commit -m "feat(eval): add golden Q&A dataset (6 types, AI-drafted)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: 리포트 집계 (eval/report.py)

**Files:**
- Create: `eval/report.py`, `tests/eval/test_report.py`

**Interfaces:**
- Produces:
  - `EvalRow(BaseModel)`: `id: str`, `qtype: str`, `question: str`, `answer: str`, `metrics: dict[str, float]`(예 groundedness/relevance/retrieval/coherence/fluency, 원문부재는 비어있을 수 있음), `passed: dict[str, bool]`(각 metric_passed), `cited: bool`, `refused: bool | None`(원문부재만).
  - `build_report(rows: list[EvalRow]) -> str` — 마크다운: 전체 요약(지표별 평균 점수 + 통과율), 목표선 대비(정확도=groundedness 통과율 vs 80%, 인용=cited율 vs 90%, 할루시네이션 방어=원문부재 refused율 vs 90%), 유형별 표.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/eval/test_report.py`:
```python
from eval.report import EvalRow, build_report


def _rows():
    return [
        EvalRow(id="q01", qtype="단일검색", question="목적?", answer="[출처 1] ...",
                metrics={"groundedness": 5.0, "relevance": 4.0}, passed={"groundedness": True, "relevance": True},
                cited=True, refused=None),
        EvalRow(id="q13", qtype="원문부재", question="아이폰?", answer="확인할 수 없습니다",
                metrics={}, passed={}, cited=False, refused=True),
    ]


def test_build_report_contains_targets_and_types():
    md = build_report(_rows())
    assert "정확도" in md and "80%" in md
    assert "인용" in md and "90%" in md
    assert "할루시네이션" in md
    assert "단일검색" in md and "원문부재" in md


def test_build_report_computes_rates():
    md = build_report(_rows())
    # groundedness 통과율 100% (1/1 적용행), 할루시네이션 방어 100% (1/1)
    assert "100" in md
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/eval/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.report'`

- [ ] **Step 3: report 구현**

Create `eval/report.py`:
```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/eval/test_report.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add eval/report.py tests/eval/test_report.py
git commit -m "feat(eval): add report aggregation vs target thresholds

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: 평가 러너 + CLI + 실제 전체 평가 (eval/runner.py, eval/run_eval.py)

**Files:**
- Create: `eval/runner.py`, `eval/run_eval.py`, `tests/eval/test_runner_smoke.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `agent.orchestrator.ask`, `eval.golden.GOLDEN_QA`, `eval.report.EvalRow/build_report`, azure-ai-evaluation 평가자, `config.settings`.
- Produces:
  - `_judge_config()` → (AzureOpenAIModelConfiguration, DefaultAzureCredential).
  - `async def evaluate_item(item: GoldenItem) -> EvalRow` — ask() 실행 → context = 상위 출처 snippet 결합. 유형이 "원문부재"면 metrics 없이 refused(부정표지 포함 여부) 판정. 아니면 Groundedness/Relevance/Retrieval/Coherence/Fluency 실행 + cited=("[출처" in answer).
  - `async def run_eval(items) -> list[EvalRow]`; `def run_eval_sync(items) -> list[EvalRow]`.

- [ ] **Step 1: runner 구현**

Create `eval/runner.py`:
```python
from __future__ import annotations

import asyncio

from azure.identity import DefaultAzureCredential
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

_NEGATION = ["없습니다", "없음", "않습니다", "않았습니다", "확인할 수 없", "확인되지 않", "제공되지 않", "포함되어 있지 않", "나와 있지 않", "찾을 수 없"]


def _judge():
    s = get_settings()
    base = s.foundry_project_endpoint.split("/api/projects")[0]
    mc = AzureOpenAIModelConfiguration(
        azure_endpoint=base,
        azure_deployment=s.foundry_chat_deployment,
        api_version=s.foundry_api_version,
    )
    cred = DefaultAzureCredential()
    return mc, cred


def _score(result: dict, metric: str) -> tuple[float, bool]:
    return float(result.get(metric, 0.0)), bool(result.get(f"{metric}_passed", False))


async def evaluate_item(item: GoldenItem) -> EvalRow:
    result = await ask(item.question)
    answer = result.answer
    context = "\n\n".join(s.snippet for s in result.sources) or "(검색 결과 없음)"

    if item.qtype == "원문부재":
        refused = any(m in answer for m in _NEGATION)
        return EvalRow(
            id=item.id, qtype=item.qtype, question=item.question, answer=answer,
            metrics={}, passed={}, cited=False, refused=refused,
        )

    mc, cred = _judge()
    evaluators = {
        "groundedness": (GroundednessEvaluator(model_config=mc, credential=cred), dict(query=item.question, context=context, response=answer)),
        "relevance": (RelevanceEvaluator(model_config=mc, credential=cred), dict(query=item.question, response=answer)),
        "retrieval": (RetrievalEvaluator(model_config=mc, credential=cred), dict(query=item.question, context=context)),
        "coherence": (CoherenceEvaluator(model_config=mc, credential=cred), dict(query=item.question, response=answer)),
        "fluency": (FluencyEvaluator(model_config=mc, credential=cred), dict(response=answer)),
    }
    metrics: dict[str, float] = {}
    passed: dict[str, bool] = {}
    for name, (ev, kwargs) in evaluators.items():
        res = ev(**kwargs)
        score, ok = _score(res, name)
        metrics[name] = score
        passed[name] = ok

    return EvalRow(
        id=item.id, qtype=item.qtype, question=item.question, answer=answer,
        metrics=metrics, passed=passed, cited=("[출처" in answer), refused=None,
    )


async def run_eval(items: list[GoldenItem] | None = None) -> list[EvalRow]:
    items = items if items is not None else GOLDEN_QA
    rows: list[EvalRow] = []
    for item in items:
        rows.append(await evaluate_item(item))
    return rows


def run_eval_sync(items: list[GoldenItem] | None = None) -> list[EvalRow]:
    return asyncio.run(run_eval(items))
```

- [ ] **Step 2: 평가자 인자 검증 (실행 중)**

Run:
```bash
uv run python -c "
from eval.golden import GOLDEN_QA
from eval.runner import evaluate_item
import asyncio
row = asyncio.run(evaluate_item(GOLDEN_QA[0]))
print('qtype:', row.qtype)
print('metrics:', row.metrics)
print('passed:', row.passed)
print('cited:', row.cited)
assert row.metrics and set(row.metrics) == {'groundedness','relevance','retrieval','coherence','fluency'}
print('OK')
"
```
Expected: 5개 지표 점수(1~5)와 통과 여부 + cited 출력, `OK`. (실 Foundry judge; 1문항 ~30~60초)
- 만약 특정 평가자가 다른 인자를 요구하면(예: Retrieval/Coherence의 키가 다름) 에러 메시지에 맞춰 해당 evaluator의 kwargs를 최소 조정. 결과 dict의 점수 키가 `<metric>`/`<metric>_passed`와 다르면 `_score`를 실제 키에 맞게 조정.

- [ ] **Step 3: 소규모 실 통합 테스트 작성**

Create `tests/eval/test_runner_smoke.py`:
```python
from eval.golden import GoldenItem
from eval.report import build_report
from eval.runner import run_eval_sync


def test_runner_small_subset_produces_scored_rows():
    items = [
        GoldenItem(id="s1", question="자산운용 평가의 목적은?", qtype="단일검색"),
        GoldenItem(id="s2", question="이 보고서에 나온 아이폰 판매량은?", qtype="원문부재"),
    ]
    rows = run_eval_sync(items)
    assert len(rows) == 2
    grounded_row = next(r for r in rows if r.qtype == "단일검색")
    assert grounded_row.metrics.get("groundedness", 0) > 0
    halluc_row = next(r for r in rows if r.qtype == "원문부재")
    assert halluc_row.refused is True
    md = build_report(rows)
    assert "평가 리포트" in md
```

- [ ] **Step 4: 통합 테스트 통과 확인**

Run: `uv run pytest tests/eval/test_runner_smoke.py -v`
Expected: PASS (1 passed). 실 Foundry+에이전트+judge (~1~2분).

- [ ] **Step 5: run_eval.py CLI 구현**

Create `eval/run_eval.py`:
```python
from __future__ import annotations

import argparse
from pathlib import Path

from eval.golden import GOLDEN_QA
from eval.report import build_report
from eval.runner import run_eval_sync


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Foundry evaluation over the golden Q&A set")
    ap.add_argument("--limit", type=int, default=None, help="평가할 최대 문항 수")
    ap.add_argument("--out", default="reports/eval-report.md")
    args = ap.parse_args()

    items = GOLDEN_QA[: args.limit] if args.limit else GOLDEN_QA
    rows = run_eval_sync(items)
    report = build_report(rows)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n리포트 저장: {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 실제 전체 평가 실행**

Run:
```bash
uv run python -m eval.run_eval
```
Expected: 18문항 전체 평가(에이전트 실행 + Foundry judge 지표) 후 `reports/eval-report.md` 생성 및 콘솔 출력. 목표선 대비 표·유형별 표 포함. (수 분 소요, 실 Azure — 승인됨)

- [ ] **Step 7: README 갱신 + 전체 회귀**

Edit `README.md` — "웹 UI 데모 (P4)" 아래에 추가:
```markdown
## 평가 (P5)
```bash
uv run python -m eval.run_eval            # 전체 Golden Q&A 평가 → reports/eval-report.md
uv run python -m eval.run_eval --limit 3  # 소규모 실행
```
Foundry judge(azure-ai-evaluation)로 Groundedness·Relevance·Retrieval·Coherence·Fluency를 측정하고, 인용율·할루시네이션 방어를 목표선과 비교합니다.
```

Run: `uv run pytest -q`
Expected: 순수 테스트(golden/report) 전부 + 통합 스모크 PASS.

- [ ] **Step 8: Commit**

```bash
git add eval/runner.py eval/run_eval.py tests/eval/test_runner_smoke.py README.md reports/eval-report.md
git commit -m "feat(eval): add Foundry-judge evaluation runner, CLI, and report

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과

- **Spec coverage:** Microsoft Foundry 평가(azure-ai-evaluation + Foundry judge, 키리스) — Groundedness/Relevance/Retrieval/Coherence/Fluency(Task 3), Citation(결정적)·할루시네이션 방어(원문부재 거부)(Task 3), Golden Q&A 6유형 AI 초안(Task 1), 목표선 대비 리포트(Task 2). 사용자 후속 리뷰 대상 데이터셋.
- **Placeholder scan:** 코드/명령 구체화. Task 3 Step 2에 평가자 인자/결과 키 실행-검증 지점 명시(버전차 대응).
- **Type consistency:** `GoldenItem`(Task 1) ↔ `evaluate_item`/`run_eval`(Task 3) ↔ `EvalRow`/`build_report`(Task 2) 일치. judge 구성은 P3와 동일한 endpoint 규칙(foundry_project_endpoint split). 에이전트는 P3 ask()만.

## 후속
- Golden Q&A 사용자 리뷰·확장(정답/기대 키워드 추가 → Similarity/F1 등).
- 다년도/다중문서 평가는 추가 문서 적재 후 강화.
- Foundry 포털 업로드(evaluate_foundry_target/FoundryEvals)로 클라우드 평가 대시보드 연동(선택).
