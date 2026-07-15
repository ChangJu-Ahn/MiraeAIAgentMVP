from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
from openpyxl import Workbook

from eval import run_eval as cli
from eval.report import EvalRow, METRICS


def _write_workbook(path: Path, item_count: int = 2, sheet: str = "질문지") -> Path:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.append(["순번", "질문", "정답"])
    for index in range(1, item_count + 1):
        worksheet.append([index, f"질문 {index}", f"정답 {index}"])
    workbook.save(path)
    workbook.close()
    return path


def _evaluated_row(item_id: str = "1") -> EvalRow:
    return EvalRow(
        id=item_id,
        qtype="미분류",
        question=f"질문 {item_id}",
        answer=f"답변 {item_id}",
        ground_truth=f"정답 {item_id}",
        context="judge context",
        metrics={metric: 4.0 for metric in METRICS},
        passed={metric: True for metric in METRICS},
        reasons={metric: f"{metric} reason" for metric in METRICS},
        cited=True,
    )


def _unexpected(*args, **kwargs):
    raise AssertionError("validate-only must not initialize normal-run dependencies")


def test_validate_only_loads_workbook_and_avoids_normal_run_dependencies(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    title = "검증용_질문지"
    workbook = _write_workbook(tmp_path / f"{title}.xlsx", item_count=2, sheet="Golden")

    assert "run_eval_sync" not in vars(cli)
    assert "setup_observability" not in vars(cli)
    assert "get_settings" not in vars(cli)

    result = cli.main(
        [title, "--validate-only"],
        docs_root=tmp_path,
        reports_root=tmp_path / "reports",
        run_eval_fn=_unexpected,
        settings_fn=_unexpected,
        setup_observability_fn=_unexpected,
    )

    output = capsys.readouterr().out
    assert result == 0
    assert title in output
    assert str(workbook) in output
    assert "Golden" in output
    assert "2" in output
    assert "질문 -> question" in output
    assert "정답 -> ground_truth" in output
    assert "순번 -> id" in output


def test_normal_run_writes_default_markdown_and_json_without_azure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    title = "Chatbot_질문지리스트_20260713"
    workbook = _write_workbook(tmp_path / f"{title}.xlsx", item_count=2, sheet="Sheet1")
    reports_root = tmp_path / "reports"
    events: list[str] = []

    def setup_observability() -> None:
        events.append("observability")

    def run_eval(items) -> list[EvalRow]:
        events.append("runner")
        assert len(items) == 1
        return [_evaluated_row(items[0].id)]

    def get_settings():
        events.append("settings")
        return SimpleNamespace(foundry_eval_deployment="judge-deployment")

    result = cli.main(
        [title, "--limit", "1"],
        docs_root=tmp_path,
        reports_root=reports_root,
        run_eval_fn=run_eval,
        settings_fn=get_settings,
        setup_observability_fn=setup_observability,
    )

    markdown_path = reports_root / f"eval-{title}.md"
    json_path = markdown_path.with_suffix(".json")
    assert result == 0
    assert events == ["observability", "runner", "settings"]
    assert markdown_path.is_file()
    assert json_path.is_file()
    markdown = markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert title in markdown
    assert str(workbook) in markdown
    assert payload["metadata"]["dataset_title"] == title
    assert payload["metadata"]["workbook_path"] == str(workbook)
    assert payload["metadata"]["sheet"] == "Sheet1"
    assert payload["metadata"]["item_count"] == 1
    assert payload["metadata"]["judge_deployment"] == "judge-deployment"
    assert payload["rows"][0]["id"] == "1"
    output = capsys.readouterr().out
    assert str(markdown_path) in output
    assert str(json_path) in output
    assert "groundedness" in output and "100.0%" in output


def test_normal_run_uses_custom_markdown_stem_for_json(tmp_path: Path):
    title = "custom-output"
    _write_workbook(tmp_path / f"{title}.xlsx", item_count=1)
    custom_markdown = tmp_path / "artifacts" / "review.md"

    result = cli.main(
        [title, "--out", str(custom_markdown)],
        docs_root=tmp_path,
        reports_root=tmp_path / "ignored",
        run_eval_fn=lambda items: [_evaluated_row(items[0].id)],
        settings_fn=lambda: SimpleNamespace(foundry_eval_deployment="judge"),
        setup_observability_fn=lambda: None,
    )

    assert result == 0
    assert custom_markdown.is_file()
    assert custom_markdown.with_suffix(".json").is_file()


def test_normal_run_checkpoints_completed_rows_and_resumes(tmp_path: Path):
    title = "resume-evaluation"
    _write_workbook(tmp_path / f"{title}.xlsx", item_count=2)
    markdown_path = tmp_path / "reports" / "resume.md"
    checkpoint_path = markdown_path.with_suffix(".partial.json")

    def fail_after_first_row(items, *, on_row=None):
        assert on_row is not None
        assert [item.id for item in items] == ["1", "2"]
        on_row(_evaluated_row("1"))
        raise RuntimeError("judge failed for item 2")

    with pytest.raises(RuntimeError, match="item 2"):
        cli.main(
            [title, "--out", str(markdown_path)],
            docs_root=tmp_path,
            reports_root=tmp_path / "reports",
            run_eval_fn=fail_after_first_row,
            settings_fn=lambda: SimpleNamespace(foundry_eval_deployment="judge"),
            setup_observability_fn=lambda: None,
        )

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert [row["id"] for row in checkpoint["rows"]] == ["1"]
    assert not markdown_path.exists()
    assert not markdown_path.with_suffix(".json").exists()

    resumed_ids: list[str] = []

    def resume_remaining(items, *, on_row=None):
        assert on_row is not None
        resumed_ids.extend(item.id for item in items)
        rows = [_evaluated_row(item.id) for item in items]
        for row in rows:
            on_row(row)
        return rows

    result = cli.main(
        [title, "--out", str(markdown_path), "--resume"],
        docs_root=tmp_path,
        reports_root=tmp_path / "reports",
        run_eval_fn=resume_remaining,
        settings_fn=lambda: SimpleNamespace(foundry_eval_deployment="judge"),
        setup_observability_fn=lambda: None,
    )

    artifact = json.loads(
        markdown_path.with_suffix(".json").read_text(encoding="utf-8")
    )
    assert result == 0
    assert resumed_ids == ["2"]
    assert [row["id"] for row in artifact["rows"]] == ["1", "2"]
    assert not checkpoint_path.exists()


def test_resume_rejects_invalid_judge_row_before_running_pending_items(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    title = "invalid-checkpoint"
    _write_workbook(tmp_path / f"{title}.xlsx", item_count=2)
    markdown_path = tmp_path / "reports" / "resume.md"
    checkpoint_path = markdown_path.with_suffix(".partial.json")

    def fail_after_first_row(items, *, on_row=None):
        assert on_row is not None
        on_row(_evaluated_row("1"))
        raise RuntimeError("stop after checkpoint")

    with pytest.raises(RuntimeError, match="stop after checkpoint"):
        cli.main(
            [title, "--out", str(markdown_path)],
            docs_root=tmp_path,
            reports_root=tmp_path / "reports",
            run_eval_fn=fail_after_first_row,
            settings_fn=lambda: SimpleNamespace(foundry_eval_deployment="judge"),
            setup_observability_fn=lambda: None,
        )

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["rows"][0]["metrics"]["groundedness"] = 6.0
    checkpoint_path.write_text(
        json.dumps(checkpoint, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        cli.main(
            [title, "--out", str(markdown_path), "--resume"],
            docs_root=tmp_path,
            reports_root=tmp_path / "reports",
            run_eval_fn=_unexpected,
            settings_fn=_unexpected,
            setup_observability_fn=_unexpected,
        )

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert "partial checkpoint를 읽을 수 없습니다" in stderr
    assert "score must be finite and within 1..5" in stderr


def test_normal_run_rejects_non_markdown_out_before_dependencies(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    title = "unsafe-output"
    _write_workbook(tmp_path / f"{title}.xlsx", item_count=1)

    with pytest.raises(SystemExit) as error:
        cli.main(
            [title, "--out", str(tmp_path / "same.json")],
            docs_root=tmp_path,
            reports_root=tmp_path / "reports",
            run_eval_fn=_unexpected,
            settings_fn=_unexpected,
            setup_observability_fn=_unexpected,
        )

    assert error.value.code == 2
    assert "--out" in capsys.readouterr().err


def test_validate_only_rejects_header_only_workbook_before_dependencies(
    tmp_path: Path,
):
    title = "header-only"
    _write_workbook(tmp_path / f"{title}.xlsx", item_count=0)

    with pytest.raises(ValueError, match="평가 문항"):
        cli.main(
            [title, "--validate-only"],
            docs_root=tmp_path,
            reports_root=tmp_path / "reports",
            run_eval_fn=_unexpected,
            settings_fn=_unexpected,
            setup_observability_fn=_unexpected,
        )


def test_empty_post_limit_dataset_errors_before_normal_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    title = "empty-limit"
    _write_workbook(tmp_path / f"{title}.xlsx", item_count=1)

    with pytest.raises(SystemExit) as error:
        cli.main(
            [title, "--limit", "0"],
            docs_root=tmp_path,
            reports_root=tmp_path / "reports",
            run_eval_fn=_unexpected,
            settings_fn=_unexpected,
            setup_observability_fn=_unexpected,
        )

    assert error.value.code == 2
    assert "평가할 문항이 없습니다" in capsys.readouterr().err
