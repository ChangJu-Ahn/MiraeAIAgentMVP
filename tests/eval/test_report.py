from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from agent.tools import RetrievedSource, TraceStep
from eval import report
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


def _rich_rows() -> list[EvalRow]:
    return [
        EvalRow(
            id="q-global",
            qtype="미분류",
            question="전체 기금 | 상위 순위\n질문",
            answer="실제 | 답변\n둘째 줄",
            ground_truth="검토된 | 정답\n핵심 포인트",
            context="judge에 전달한 정확한 context\n두 번째 문단",
            metrics={
                "groundedness": 2.0,
                "relevance": 4.0,
                "similarity": 2.0,
                "coherence": 4.0,
                "fluency": 4.0,
            },
            passed={
                "groundedness": False,
                "relevance": True,
                "similarity": False,
                "coherence": True,
                "fluency": True,
            },
            reasons={
                "groundedness": "근거 | 부족\n상세",
                "relevance": "질문에 관련됨",
                "similarity": "정답 핵심 누락",
                "coherence": "구조가 명확함",
                "fluency": "표현이 자연스러움",
            },
            steps=[
                TraceStep(
                    tool="search_tables",
                    query="점수 | 순위",
                    n_hits=5,
                    odata_filter="year eq 2025",
                )
            ],
            sources=[
                RetrievedSource(
                    n=1,
                    index="table|index",
                    section_path="기금|평가/점수",
                    page_physical=42,
                    chunk_type="table",
                    snippet="스니펫 | 한글\n둘째 줄",
                    score=0.91,
                )
            ],
            cited=False,
        ),
        EvalRow(
            id="q-absence",
            qtype="원문부재",
            question="자료에 없는 값은?",
            answer="제공된 자료에서 확인할 수 없습니다.",
            ground_truth="자료에 없다고 답한다.",
            context="(검색 결과 없음)",
            metrics={metric: 5.0 for metric in report.METRICS},
            passed={metric: True for metric in report.METRICS},
            reasons={metric: f"{metric} 통과" for metric in report.METRICS},
            cited=False,
            refused=True,
        ),
    ]


def _metadata():
    return report.EvalMetadata(
        dataset_title="Chatbot_질문지리스트_20260713",
        workbook_path="docs/Chatbot_질문지리스트_20260713.xlsx",
        sheet="Sheet1",
        item_count=2,
        evaluated_at="2026-07-14T10:30:00+00:00",
        judge_deployment="judge-gpt-4.1",
    )


def test_build_artifact_and_rich_report_include_metadata_metrics_and_details():
    artifact = report.build_artifact(rows=_rich_rows(), metadata=_metadata())

    assert artifact.metadata.context_snippet_limit == 300
    assert "300" in artifact.metadata.context_snippet_note
    assert artifact.summary
    assert artifact.recommendations

    md = report.build_report(artifact)

    assert "Chatbot_질문지리스트_20260713" in md
    assert "docs/Chatbot_질문지리스트_20260713.xlsx" in md
    assert "Sheet1" in md
    assert "2026-07-14T10:30:00+00:00" in md
    assert "judge-gpt-4.1" in md
    assert "300" in md and "truncated" in md
    for metric in report.METRICS:
        assert f"| {metric} |" in md
    assert "| groundedness | 3.50 | 50.0% |" in md
    assert "근거 인용율" in md and "0.0%" in md
    assert "원문부재 거부율" in md and "100.0%" in md
    assert "미분류" in md
    assert "| q-global | 미분류 | 2.00 / FAIL | 4.00 / PASS | 2.00 / FAIL |" in md
    assert "## 실패 군집" in md
    assert "evidence-context" in md
    assert "ground-truth-key-points" in md
    assert "global-coverage" in md
    assert "## 실패 문항 상세" in md
    assert "### q-global" in md
    assert "### q-absence" not in md
    assert "전체 기금 | 상위 순위\n질문" in md
    assert "검토된 | 정답\n핵심 포인트" in md
    assert "실제 | 답변\n둘째 줄" in md
    assert "judge에 전달한 정확한 context\n두 번째 문단" in md
    assert "근거 \\| 부족<br>상세" in md
    assert "점수 \\| 순위" in md
    assert "year eq 2025" in md
    assert "table\\|index" in md
    assert "기금\\|평가/점수" in md
    assert "스니펫 \\| 한글<br>둘째 줄" in md
    assert "## 에이전트 시스템 개선 제안" in md
    assert "1순위" in md and "평가 데이터/trace 가시성" in md
    assert "2순위" in md and "global-scope" in md and "q-global" in md
    assert "3순위" in md
    for field in (
        "fund_name",
        "year",
        "metric",
        "score",
        "max_score",
        "grade",
        "page",
        "source_chunk",
    ):
        assert field in md
    assert "sortable index" in md and "aggregation tool" in md
    assert "4순위" in md and "같은 workbook" in md
    assert "일반 사실 질문은 top-5를 유지" in md
    assert "TOC/metadata fan-out" in md
    assert "전체 top-k를 일괄 확대하지" in md
    assert "PASS" in md and "FAIL" in md
    assert "✅" not in md and "❌" not in md


def test_build_report_uses_na_when_a_rate_has_no_relevant_question_type():
    ordinary = _rich_rows()[0].model_copy(
        update={
            "question": "일반 질문",
            "steps": [],
            "passed": {metric: True for metric in report.METRICS},
            "metrics": {metric: 4.0 for metric in report.METRICS},
            "cited": True,
        }
    )
    absence = _rich_rows()[1]

    ordinary_md = build_report([ordinary])
    absence_md = build_report([absence])

    assert "| 할루시네이션 방어(원문부재 거부율) | N/A | 90% | N/A |" in ordinary_md
    assert "| 근거 인용율 | N/A | 90% | N/A |" in absence_md


def test_artifact_json_is_pretty_unicode_and_lossless(tmp_path: Path):
    artifact = report.build_artifact(rows=_rich_rows(), metadata=_metadata())

    payload = report.artifact_to_json(artifact)
    decoded = json.loads(payload)

    assert payload.startswith("{\n")
    assert "전체 기금" in payload
    assert "\\uc804" not in payload
    assert decoded == artifact.model_dump(mode="json")
    assert decoded["rows"][0]["context"] == "judge에 전달한 정확한 context\n두 번째 문단"
    assert decoded["rows"][0]["reasons"]["groundedness"] == "근거 | 부족\n상세"
    assert decoded["rows"][0]["steps"][0]["n_hits"] == 5
    assert decoded["rows"][0]["sources"][0]["snippet"] == "스니펫 | 한글\n둘째 줄"

    output = tmp_path / "artifact.json"
    written = report.write_artifact_json(artifact, output)

    assert written == output
    assert output.read_text(encoding="utf-8") == payload
    assert report.EvalArtifact.model_validate_json(payload) == artifact
    assert payload.endswith("}")


@pytest.mark.parametrize("field_name", ["metrics", "passed", "reasons"])
def test_build_artifact_requires_all_five_metric_fields(field_name: str):
    rows = _rich_rows()
    getattr(rows[0], field_name).pop("fluency")

    with pytest.raises(ValueError, match=r"q-global.*fluency"):
        report.build_artifact(rows=rows, metadata=_metadata())


def test_build_artifact_rejects_out_of_range_metric_score():
    rows = _rich_rows()
    rows[0].metrics["groundedness"] = 0.0

    with pytest.raises(ValueError, match=r"q-global.*1\.\.5"):
        report.build_artifact(rows=rows, metadata=_metadata())


def test_build_artifact_rejects_pass_flag_inconsistent_with_threshold():
    rows = _rich_rows()
    rows[0].passed["groundedness"] = True

    with pytest.raises(ValueError, match=r"q-global.*groundedness.*threshold"):
        report.build_artifact(rows=rows, metadata=_metadata())


def test_artifact_json_rejects_non_finite_metric_scores():
    artifact = report.build_artifact(rows=_rich_rows(), metadata=_metadata())
    artifact.rows[0].metrics["groundedness"] = math.nan

    with pytest.raises(ValueError, match="Out of range float"):
        report.artifact_to_json(artifact)
