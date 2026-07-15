from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from agent.tools import RetrievedSource, TraceStep
from eval.analysis import FailureCluster, analyze_rows

METRICS = ["groundedness", "relevance", "similarity", "coherence", "fluency"]


class EvalRow(BaseModel):
    id: str
    qtype: str
    question: str
    answer: str
    ground_truth: str | None = None
    context: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    passed: dict[str, bool] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)
    steps: list[TraceStep] = Field(default_factory=list)
    sources: list[RetrievedSource] = Field(default_factory=list)
    cited: bool = False
    refused: bool | None = None


def validate_eval_rows(rows: list[EvalRow]) -> None:
    expected = set(METRICS)
    for row in rows:
        for field_name in ("metrics", "passed", "reasons"):
            actual = set(getattr(row, field_name))
            if actual != expected:
                missing = ", ".join(sorted(expected - actual)) or "none"
                unexpected = ", ".join(sorted(actual - expected)) or "none"
                raise ValueError(
                    f"row {row.id} {field_name} must contain exactly five metrics; "
                    f"missing: {missing}; unexpected: {unexpected}"
                )
        for metric, score in row.metrics.items():
            if not math.isfinite(score) or not 1.0 <= score <= 5.0:
                raise ValueError(
                    f"row {row.id} {metric} score must be finite and within 1..5"
                )
            if row.passed[metric] != (score >= 3.0):
                raise ValueError(
                    f"row {row.id} {metric} pass flag is inconsistent with threshold 3"
                )
        for metric, reason in row.reasons.items():
            if not reason.strip():
                raise ValueError(f"row {row.id} {metric} reason must be nonblank")


class EvalMetadata(BaseModel):
    dataset_title: str
    workbook_path: str
    sheet: str
    item_count: int
    evaluated_at: str
    judge_deployment: str
    context_snippet_limit: Literal[300] = 300
    context_snippet_note: str = "Stored source snippets are truncated to 300 chars."

    @field_validator("evaluated_at")
    @classmethod
    def _validate_evaluated_at(cls, value: str) -> str:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class EvalArtifact(BaseModel):
    metadata: EvalMetadata
    rows: list[EvalRow]
    clusters: list[FailureCluster] = Field(default_factory=list)
    summary: str
    recommendations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_evaluation_contract(self) -> EvalArtifact:
        if self.metadata.item_count != len(self.rows):
            raise ValueError(
                "metadata item_count must match the number of evaluation rows"
            )
        validate_eval_rows(self.rows)
        return self


def _rate(flags: list[bool]) -> float | None:
    if not flags:
        return None
    return 100.0 * sum(1 for flag in flags if flag) / len(flags)


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _format_rate(flags: list[bool], digits: int = 1) -> str:
    rate = _rate(flags)
    return "N/A" if rate is None else f"{rate:.{digits}f}%"


def _metric_passed(row: EvalRow, metric: str) -> bool | None:
    if metric in row.passed:
        return row.passed[metric]
    score = row.metrics.get(metric)
    return None if score is None else score >= 3.0


def _failed_metrics(row: EvalRow) -> list[str]:
    return [metric for metric in METRICS if _metric_passed(row, metric) is False]


def _table_cell(value: object | None) -> str:
    if value is None:
        return "N/A"
    return str(value).replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")


def _code_block(value: str | None) -> list[str]:
    content = value if value not in {None, ""} else "(없음)"
    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return [f"{fence}text", content, fence]


def _metric_summary(rows: list[EvalRow]) -> str:
    parts: list[str] = []
    for metric in METRICS:
        values = [row.metrics[metric] for row in rows if metric in row.metrics]
        flags = [
            passed
            for row in rows
            if metric in row.metrics
            for passed in [_metric_passed(row, metric)]
            if passed is not None
        ]
        average = _avg(values)
        if average is None:
            parts.append(f"{metric}=N/A")
        else:
            parts.append(f"{metric}={average:.2f}/{_format_rate(flags)}")
    return "; ".join(parts)


def _observed_ids(clusters: list[FailureCluster], code: str | None = None) -> list[str]:
    return sorted(
        {
            item_id
            for cluster in clusters
            if code is None or cluster.code == code
            for item_id in cluster.item_ids
        }
    )


def _id_evidence(item_ids: list[str]) -> str:
    return ", ".join(item_ids) if item_ids else "관찰 ID 없음"


def _recommendations(rows: list[EvalRow], clusters: list[FailureCluster]) -> list[str]:
    failed_ids = _observed_ids(clusters)
    global_ids = _observed_ids(clusters, "global-coverage")
    evaluated_ids = sorted({row.id for row in rows})
    return [
        "1순위 - 평가 데이터/trace 가시성: "
        f"{_id_evidence(failed_ids)}의 ground_truth, exact judge context, judge reason, "
        "검색 trace와 source를 같은 artifact에 보존합니다.",
        "2순위 - global-scope 분류와 coverage guard: "
        f"{_id_evidence(global_ids)}를 우선 점검합니다. 전체 top-k를 일괄 확대하지 않고, "
        "일반 사실 질문은 top-5를 유지하며 cross-section 비교는 TOC/metadata fan-out, "
        "전역 집계와 순위는 정규화 레코드와 numeric aggregation tool로 처리합니다.",
        "3순위 - 정규화 및 집계 경로: "
        "fund_name/year/metric/score/max_score/grade/page/source_chunk 필드, "
        "sortable index, numeric aggregation tool을 ingest 및 retrieval 경로에 설계합니다.",
        "4순위 - 동일 데이터 재평가: "
        f"{_id_evidence(evaluated_ids)}를 포함한 같은 workbook으로 변경 전후를 재평가합니다.",
    ]


def build_artifact(
    *,
    metadata: EvalMetadata,
    rows: list[EvalRow],
    clusters: list[FailureCluster] | None = None,
) -> EvalArtifact:
    resolved_clusters = clusters if clusters is not None else analyze_rows(rows)
    return EvalArtifact(
        metadata=metadata,
        rows=rows,
        clusters=resolved_clusters,
        summary=_metric_summary(rows),
        recommendations=_recommendations(rows, resolved_clusters),
    )


def artifact_to_json(artifact: EvalArtifact) -> str:
    return json.dumps(
        artifact.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )


def write_artifact_json(artifact: EvalArtifact, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact_to_json(artifact), encoding="utf-8")
    return path


def _append_metadata(lines: list[str], metadata: EvalMetadata) -> None:
    lines += [
        "## 평가 메타데이터",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 데이터셋 제목 | {_table_cell(metadata.dataset_title)} |",
        f"| workbook 파일 | {_table_cell(metadata.workbook_path)} |",
        f"| sheet | {_table_cell(metadata.sheet)} |",
        f"| 문항 수 | {metadata.item_count} |",
        f"| 평가 시각 | {_table_cell(metadata.evaluated_at)} |",
        f"| judge deployment | {_table_cell(metadata.judge_deployment)} |",
        f"| source snippet 제한 | {_table_cell(metadata.context_snippet_note)} |",
        "",
    ]


def _append_targets(lines: list[str], rows: list[EvalRow]) -> None:
    grounded_flags = [
        passed
        for row in rows
        if row.qtype != "원문부재"
        for passed in [_metric_passed(row, "groundedness")]
        if passed is not None
    ]
    cited_flags = [row.cited for row in rows if row.qtype != "원문부재"]
    refused_flags = [bool(row.refused) for row in rows if row.qtype == "원문부재"]

    def target_row(label: str, flags: list[bool], target: float) -> str:
        rate = _rate(flags)
        result = "N/A" if rate is None else f"{rate:.1f}%"
        status = "N/A" if rate is None else ("PASS" if rate >= target else "FAIL")
        return f"| {label} | {result} | {target:.0f}% | {status} |"

    lines += [
        "## 목표선 대비",
        "| 지표 | 결과 | 목표 | 판정 |",
        "|---|---|---|---|",
        target_row("정확도(groundedness 통과율)", grounded_flags, 80),
        target_row("근거 인용율", cited_flags, 90),
        target_row("할루시네이션 방어(원문부재 거부율)", refused_flags, 90),
        "",
    ]


def _append_metric_results(lines: list[str], rows: list[EvalRow]) -> None:
    lines += [
        "## 지표별 평균 점수 (1~5, Foundry judge)",
        "| 지표 | 평균 | 통과율 | 통과 기준 |",
        "|---|---|---|---|",
    ]
    for metric in METRICS:
        values = [row.metrics[metric] for row in rows if metric in row.metrics]
        flags = [
            passed
            for row in rows
            if metric in row.metrics
            for passed in [_metric_passed(row, metric)]
            if passed is not None
        ]
        average = _avg(values)
        average_text = "N/A" if average is None else f"{average:.2f}"
        lines.append(f"| {metric} | {average_text} | {_format_rate(flags)} | 3.0 |")
    lines.append("")


def _append_type_results(lines: list[str], rows: list[EvalRow]) -> None:
    lines += [
        "## 유형별 결과",
        "| 유형 | 문항수 | groundedness 통과 | 인용율 |",
        "|---|---|---|---|",
    ]
    for qtype in sorted({row.qtype for row in rows}):
        subset = [row for row in rows if row.qtype == qtype]
        grounded_flags = [
            passed
            for row in subset
            if row.qtype != "원문부재"
            for passed in [_metric_passed(row, "groundedness")]
            if passed is not None
        ]
        cited_flags = [row.cited for row in subset if row.qtype != "원문부재"]
        lines.append(
            f"| {_table_cell(qtype)} | {len(subset)} | "
            f"{_format_rate(grounded_flags, 0)} | {_format_rate(cited_flags, 0)} |"
        )
    lines.append("")


def _metric_cell(row: EvalRow, metric: str) -> str:
    score = row.metrics.get(metric)
    passed = _metric_passed(row, metric)
    if score is None or passed is None:
        return "N/A"
    return f"{score:.2f} / {'PASS' if passed else 'FAIL'}"


def _append_question_results(lines: list[str], rows: list[EvalRow]) -> None:
    lines += [
        "## 문항별 결과",
        "| ID | 유형 | groundedness | relevance | similarity | coherence | fluency |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        metric_cells = " | ".join(_metric_cell(row, metric) for metric in METRICS)
        lines.append(
            f"| {_table_cell(row.id)} | {_table_cell(row.qtype)} | {metric_cells} |"
        )
    lines.append("")


def _append_clusters(lines: list[str], clusters: list[FailureCluster]) -> None:
    lines.append("## 실패 군집")
    if not clusters:
        lines += ["관찰된 실패 군집이 없습니다.", ""]
        return
    lines += [
        "| 우선순위 | 코드 | 제목 | 문항 ID | 근거 | 권고 |",
        "|---|---|---|---|---|---|",
    ]
    for cluster in clusters:
        lines.append(
            f"| {cluster.priority} | {_table_cell(cluster.code)} | "
            f"{_table_cell(cluster.title)} | {_table_cell(', '.join(cluster.item_ids))} | "
            f"{_table_cell(chr(10).join(cluster.evidence))} | "
            f"{_table_cell(cluster.recommendation)} |"
        )
    lines.append("")


def _append_failure_details(lines: list[str], rows: list[EvalRow]) -> None:
    failed_rows = [row for row in rows if _failed_metrics(row)]
    lines.append("## 실패 문항 상세")
    if not failed_rows:
        lines += ["실패 지표가 있는 문항이 없습니다.", ""]
        return

    for row in failed_rows:
        failed = _failed_metrics(row)
        lines += [
            f"### {row.id}",
            f"- 유형: {row.qtype}",
            f"- 실패 지표: {', '.join(failed)}",
            "",
            "#### 질문",
            *_code_block(row.question),
            "",
            "#### 검토 정답 (ground_truth)",
            *_code_block(row.ground_truth),
            "",
            "#### 실제 답변",
            *_code_block(row.answer),
            "",
            "#### Judge context (exact)",
            *_code_block(row.context),
            "",
            "#### Judge 판정 이유",
            "| 지표 | 점수 | 판정 | 이유 |",
            "|---|---|---|---|",
        ]
        for metric in METRICS:
            score = row.metrics.get(metric)
            passed = _metric_passed(row, metric)
            score_text = "N/A" if score is None else f"{score:.2f}"
            status = "N/A" if passed is None else ("PASS" if passed else "FAIL")
            lines.append(
                f"| {metric} | {score_text} | {status} | "
                f"{_table_cell(row.reasons.get(metric, ''))} |"
            )

        lines += ["", "#### 검색 trace"]
        if row.steps:
            lines += [
                "| tool | query | filter | n_hits |",
                "|---|---|---|---|",
            ]
            for step in row.steps:
                lines.append(
                    f"| {_table_cell(step.tool)} | {_table_cell(step.query)} | "
                    f"{_table_cell(step.odata_filter)} | {step.n_hits} |"
                )
        else:
            lines.append("검색 trace가 없습니다.")

        lines += ["", "#### 출처"]
        if row.sources:
            lines += [
                "| 번호 | index | path | page | snippet |",
                "|---|---|---|---|---|",
            ]
            for source in row.sources:
                lines.append(
                    f"| {source.n} | {_table_cell(source.index)} | "
                    f"{_table_cell(source.section_path)} | {source.page_physical} | "
                    f"{_table_cell(source.snippet)} |"
                )
        else:
            lines.append("기록된 출처가 없습니다.")
        lines.append("")


def _append_recommendations(lines: list[str], recommendations: list[str]) -> None:
    lines.append("## 에이전트 시스템 개선 제안")
    for index, recommendation in enumerate(recommendations, start=1):
        lines.append(f"{index}. {recommendation}")
    lines.append("")


def build_report(artifact_or_rows: EvalArtifact | list[EvalRow]) -> str:
    if isinstance(artifact_or_rows, EvalArtifact):
        metadata = artifact_or_rows.metadata
        rows = artifact_or_rows.rows
        clusters = artifact_or_rows.clusters
        recommendations = artifact_or_rows.recommendations
    else:
        metadata = None
        rows = artifact_or_rows
        clusters = analyze_rows(rows)
        recommendations = _recommendations(rows, clusters)

    lines: list[str] = ["# 평가 리포트 (Foundry Evaluation)", ""]
    lines.append(f"- 총 문항: {len(rows)}")
    lines.append("")
    if metadata is not None:
        _append_metadata(lines, metadata)
    _append_targets(lines, rows)
    _append_metric_results(lines, rows)
    _append_type_results(lines, rows)
    _append_question_results(lines, rows)
    _append_clusters(lines, clusters)
    _append_failure_details(lines, rows)
    _append_recommendations(lines, recommendations)
    return "\n".join(lines).rstrip() + "\n"
