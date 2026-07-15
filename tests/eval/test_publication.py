from __future__ import annotations

import json
from pathlib import Path

from agent.tools import RetrievedSource, TraceStep
from eval.publication import build_public_snapshot, main, publish_evaluation
from eval.report import EvalArtifact, EvalMetadata, EvalRow, METRICS, artifact_to_json


PUBLIC_ROW_KEYS = {
    "id",
    "qtype",
    "question",
    "ground_truth",
    "answer",
    "metrics",
    "passed",
    "reasons",
    "cited",
}


def _artifact() -> EvalArtifact:
    row = EvalRow(
        id="1",
        qtype="단일검색",
        question="평가 질문",
        answer="평가 답변 [출처 1]",
        ground_truth="검토 정답",
        context="공개하면 안 되는 judge context",
        metrics={metric: 4.0 for metric in METRICS},
        passed={metric: True for metric in METRICS},
        reasons={metric: f"{metric} 판정 근거" for metric in METRICS},
        steps=[
            TraceStep(
                tool="search_narrative",
                query="내부 검색어",
                n_hits=1,
                odata_filter="year eq 2025",
            )
        ],
        sources=[
            RetrievedSource(
                n=1,
                index="internal-index",
                section_path="내부 경로",
                page_physical=7,
                chunk_type="text",
                snippet="공개하면 안 되는 source snippet",
                score=0.9,
            )
        ],
        cited=True,
    )
    return EvalArtifact(
        metadata=EvalMetadata(
            dataset_title="고객 평가셋",
            workbook_path="Docs/customer.xlsx",
            sheet="Sheet1",
            item_count=1,
            evaluated_at="2026-07-15T00:00:00+00:00",
            judge_deployment="judge",
        ),
        rows=[row],
        summary="internal summary",
        recommendations=["internal recommendation"],
    )


def test_build_public_snapshot_projects_only_approved_fields():
    snapshot = build_public_snapshot(_artifact())

    assert set(snapshot) == {"schema_version", "metadata", "metrics", "rows"}
    assert snapshot["schema_version"] == 1
    assert set(snapshot["metadata"]) == {
        "dataset_title",
        "item_count",
        "evaluated_at",
        "judge_deployment",
        "pass_threshold",
    }
    assert set(snapshot["rows"][0]) == PUBLIC_ROW_KEYS
    serialized = json.dumps(snapshot, ensure_ascii=False)
    for forbidden in (
        "judge context",
        "internal-index",
        "내부 검색어",
        "source snippet",
        "internal recommendation",
        "odata_filter",
    ):
        assert forbidden not in serialized


def test_build_public_snapshot_summarizes_every_evaluator_in_stable_order():
    snapshot = build_public_snapshot(_artifact())

    assert snapshot["metrics"] == [
        {
            "name": metric,
            "average": 4.0,
            "pass_rate": 100.0,
            "passed": 1,
            "total": 1,
        }
        for metric in METRICS
    ]


def test_build_public_snapshot_fixes_display_precision_before_javascript():
    source = _artifact()
    rows = []
    for index in range(16):
        row = source.rows[0].model_copy(deep=True)
        row.id = str(index + 1)
        if index >= 13:
            row.metrics["similarity"] = 2.0
            row.passed["similarity"] = False
        rows.append(row)
    artifact = EvalArtifact(
        metadata=source.metadata.model_copy(update={"item_count": 16}),
        rows=rows,
        summary=source.summary,
    )

    snapshot = build_public_snapshot(artifact)

    similarity = next(
        metric for metric in snapshot["metrics"] if metric["name"] == "similarity"
    )
    assert similarity["average"] == 3.62
    assert similarity["pass_rate"] == 81.2


def test_publish_evaluation_writes_valid_utf8_json_atomically(tmp_path: Path):
    input_path = tmp_path / "raw" / "artifact.json"
    output_path = tmp_path / "public" / "evaluation-data.json"
    input_path.parent.mkdir()
    input_path.write_text(artifact_to_json(_artifact()), encoding="utf-8")

    written = publish_evaluation(input_path, output_path)

    assert written == output_path
    assert not output_path.with_name(f"{output_path.name}.tmp").exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["dataset_title"] == "고객 평가셋"
    assert payload["rows"][0]["question"] == "평가 질문"


def test_publication_cli_accepts_input_and_output_paths(tmp_path: Path):
    input_path = tmp_path / "artifact.json"
    output_path = tmp_path / "nested" / "public.json"
    input_path.write_text(artifact_to_json(_artifact()), encoding="utf-8")

    result = main([str(input_path), str(output_path)])

    assert result == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["schema_version"] == 1