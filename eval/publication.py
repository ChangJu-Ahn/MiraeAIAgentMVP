from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from eval.report import EvalArtifact, METRICS, validate_eval_rows


def build_public_snapshot(artifact: EvalArtifact) -> dict[str, object]:
    validate_eval_rows(artifact.rows)
    if not artifact.rows:
        raise ValueError("public evaluation snapshot requires at least one row")

    metric_summaries: list[dict[str, object]] = []
    for metric in METRICS:
        values = [row.metrics[metric] for row in artifact.rows]
        flags = [row.passed[metric] for row in artifact.rows]
        metric_summaries.append(
            {
                "name": metric,
                "average": round(sum(values) / len(values), 2),
                "pass_rate": round(100.0 * sum(flags) / len(flags), 1),
                "passed": sum(flags),
                "total": len(flags),
            }
        )

    return {
        "schema_version": 1,
        "metadata": {
            "dataset_title": artifact.metadata.dataset_title,
            "item_count": artifact.metadata.item_count,
            "evaluated_at": artifact.metadata.evaluated_at,
            "judge_deployment": artifact.metadata.judge_deployment,
            "pass_threshold": 3.0,
        },
        "metrics": metric_summaries,
        "rows": [
            {
                "id": row.id,
                "qtype": row.qtype,
                "question": row.question,
                "ground_truth": row.ground_truth,
                "answer": row.answer,
                "metrics": row.metrics,
                "passed": row.passed,
                "reasons": row.reasons,
                "cited": row.cited,
            }
            for row in artifact.rows
        ],
    }


def publish_evaluation(input_path: Path, output_path: Path) -> Path:
    artifact = EvalArtifact.model_validate_json(input_path.read_text(encoding="utf-8"))
    snapshot = build_public_snapshot(artifact)
    serialized = json.dumps(
        snapshot,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f"{output_path.name}.tmp")
    temporary_path.write_text(serialized, encoding="utf-8")
    temporary_path.replace(output_path)
    return output_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish an allowlisted customer-facing evaluation snapshot"
    )
    parser.add_argument("input", type=Path, help="validated EvalArtifact JSON")
    parser.add_argument("output", type=Path, help="public snapshot JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_path = publish_evaluation(args.input, args.output)
    print(f"Public evaluation snapshot: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())