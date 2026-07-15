from __future__ import annotations

import argparse
import inspect
import json
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from eval.dataset import load_golden_workbook, resolve_workbook

if TYPE_CHECKING:
    from config.settings import Settings
    from eval.golden import GoldenItem
    from eval.report import EvalRow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Foundry evaluation over a validated Excel golden set"
    )
    parser.add_argument("title", help="Docs 아래 XLSX 파일의 확장자 없는 제목")
    parser.add_argument("--limit", type=int, default=None, help="평가할 최대 문항 수")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Excel 계약만 검증하고 평가 호출 전에 종료",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="기존 partial checkpoint의 완료 문항을 재사용",
    )
    parser.add_argument("--out", default=None, help="Markdown 출력 경로")
    return parser


def _safe_output_title(title: str) -> str:
    safe = re.sub(r"[^\w.-]+", "-", title, flags=re.UNICODE).strip("-._")
    return safe or "dataset"


def _print_validation(title: str, workbook: Path, items: list[GoldenItem]) -> None:
    sheet = items[0].sheet if items else "(문항 없음)"
    print(f"데이터셋 제목: {title}")
    print(f"workbook 경로: {workbook}")
    print(f"sheet: {sheet}")
    print(f"문항 수: {len(items)}")
    print("논리 매핑:")
    print("- 질문 -> question")
    print("- 정답 -> ground_truth")
    print("- 순번 -> id")


def _checkpoint_contract(
    title: str,
    workbook: Path,
    items: list[GoldenItem],
) -> dict[str, object]:
    return {
        "version": 1,
        "dataset_title": title,
        "workbook_path": str(workbook.resolve()),
        "items": [
            {
                "id": item.id,
                "question": item.question,
                "qtype": item.qtype,
                "ground_truth": item.ground_truth,
                "sheet": item.sheet,
                "row_number": item.row_number,
            }
            for item in items
        ],
    }


def _write_checkpoint(
    path: Path,
    *,
    contract: dict[str, object],
    rows: list[EvalRow],
) -> None:
    payload = {
        **contract,
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(serialized, encoding="utf-8")
    temporary_path.replace(path)


def _load_checkpoint(
    path: Path,
    *,
    contract: dict[str, object],
) -> list[EvalRow]:
    from eval.report import EvalRow, validate_eval_rows

    payload = json.loads(path.read_text(encoding="utf-8"))
    actual_contract = {key: payload.get(key) for key in contract}
    if actual_contract != contract:
        raise ValueError("partial checkpoint does not match the selected workbook")

    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("partial checkpoint rows must be a list")
    rows = [EvalRow.model_validate(row) for row in raw_rows]
    expected_ids = [str(item["id"]) for item in contract["items"]]
    row_ids = [row.id for row in rows]
    if row_ids != expected_ids[: len(row_ids)]:
        raise ValueError("partial checkpoint rows must be an ordered item prefix")
    validate_eval_rows(rows)
    return rows


def main(
    argv: Sequence[str] | None = None,
    *,
    docs_root: Path = Path("Docs"),
    reports_root: Path = Path("reports"),
    run_eval_fn: Callable[..., list[EvalRow]] | None = None,
    settings_fn: Callable[[], Settings] | None = None,
    setup_observability_fn: Callable[[], None] | None = None,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    workbook = resolve_workbook(args.title, root=docs_root)
    items = load_golden_workbook(workbook)
    if args.validate_only:
        _print_validation(args.title, workbook, items)
        return 0

    if args.limit is not None and args.limit < 0:
        parser.error("--limit는 0 이상의 정수여야 합니다")
    selected_items = items[: args.limit] if args.limit is not None else items
    if not selected_items:
        parser.error("평가할 문항이 없습니다 (--limit 적용 후)")

    if args.out is None:
        markdown_path = reports_root / f"eval-{_safe_output_title(args.title)}.md"
    else:
        markdown_path = Path(args.out)
        if markdown_path.suffix.casefold() != ".md":
            parser.error("--out은 .md 확장자의 Markdown 경로여야 합니다")
    json_path = markdown_path.with_suffix(".json")
    checkpoint_path = markdown_path.with_suffix(".partial.json")
    try:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        parser.error(f"출력 디렉터리를 준비할 수 없습니다: {error}")

    contract = _checkpoint_contract(args.title, workbook, selected_items)
    completed_rows: list[EvalRow] = []
    if args.resume:
        if not checkpoint_path.is_file():
            parser.error(f"재개할 partial checkpoint가 없습니다: {checkpoint_path}")
        try:
            completed_rows = _load_checkpoint(
                checkpoint_path,
                contract=contract,
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            parser.error(f"partial checkpoint를 읽을 수 없습니다: {error}")
        print(
            f"checkpoint 재개: {len(completed_rows)}/{len(selected_items)}개 완료"
        )
    else:
        checkpoint_path.unlink(missing_ok=True)

    pending_items = selected_items[len(completed_rows) :]

    def on_row(row: EvalRow) -> None:
        expected_item = selected_items[len(completed_rows)]
        if row.id != expected_item.id:
            raise ValueError(
                f"runner returned item {row.id!r}; expected {expected_item.id!r}"
            )
        completed_rows.append(row)
        _write_checkpoint(
            checkpoint_path,
            contract=contract,
            rows=completed_rows,
        )
        print(
            f"평가 완료: item={row.id} "
            f"({len(completed_rows)}/{len(selected_items)})",
            flush=True,
        )

    if pending_items:
        if setup_observability_fn is None:
            from agent.observability import setup_observability

            setup_observability_fn = setup_observability
        setup_observability_fn()

        if run_eval_fn is None:
            from eval.runner import run_eval_sync

            run_eval_fn = run_eval_sync
        parameters = inspect.signature(run_eval_fn).parameters.values()
        supports_on_row = any(
            parameter.name == "on_row"
            or parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        if supports_on_row:
            new_rows = run_eval_fn(pending_items, on_row=on_row)
        else:
            new_rows = run_eval_fn(pending_items)
        if [row.id for row in new_rows] != [item.id for item in pending_items]:
            raise ValueError("runner results do not match the pending item order")
        completed_ids = {row.id for row in completed_rows}
        for row in new_rows:
            if row.id not in completed_ids:
                on_row(row)
                completed_ids.add(row.id)

    rows = completed_rows

    if settings_fn is None:
        from config.settings import get_settings

        settings_fn = get_settings
    settings = settings_fn()

    from eval.report import (
        EvalMetadata,
        build_artifact,
        build_report,
        write_artifact_json,
    )

    metadata = EvalMetadata(
        dataset_title=args.title,
        workbook_path=str(workbook),
        sheet=selected_items[0].sheet or "(unknown)",
        item_count=len(selected_items),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        judge_deployment=settings.foundry_eval_deployment,
    )
    artifact = build_artifact(metadata=metadata, rows=rows)
    report = build_report(artifact)

    markdown_path.write_text(report, encoding="utf-8")
    write_artifact_json(artifact, json_path)
    checkpoint_path.unlink(missing_ok=True)
    print(f"Markdown 저장: {markdown_path}")
    print(f"JSON 저장: {json_path}")
    print(f"지표 요약: {artifact.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
