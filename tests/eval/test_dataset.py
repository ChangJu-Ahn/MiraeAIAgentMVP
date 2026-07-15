from pathlib import Path

import pytest
from openpyxl import Workbook

from eval.dataset import load_golden_workbook, resolve_workbook


REAL_WORKBOOK = (
    Path(__file__).resolve().parents[2]
    / "Docs"
    / "Chatbot_질문지리스트_20260713.xlsx"
)


def _write_workbook(path: Path, rows: list[list[object]], sheet: str = "Golden") -> Path:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()
    return path


def test_resolve_workbook_maps_title_to_xlsx_under_root(tmp_path: Path):
    workbook = tmp_path / "golden-set.xlsx"
    workbook.touch()

    assert resolve_workbook("golden-set", root=tmp_path) == workbook


def test_resolve_workbook_defaults_to_tracked_docs_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    docs = tmp_path / "Docs"
    docs.mkdir()
    workbook = docs / "golden-set.xlsx"
    workbook.touch()
    monkeypatch.chdir(tmp_path)

    assert resolve_workbook("golden-set") == Path("Docs/golden-set.xlsx")


def test_resolve_workbook_rejects_symlink_outside_root(tmp_path: Path):
    docs = tmp_path / "Docs"
    docs.mkdir()
    outside = tmp_path / "outside.xlsx"
    outside.touch()
    (docs / "linked.xlsx").symlink_to(outside)

    with pytest.raises(ValueError, match="Docs 루트"):
        resolve_workbook("linked", root=docs)


@pytest.mark.parametrize(
    "title",
    [
        "",
        "   ",
        ".",
        "..",
        "../golden-set",
        "folder/golden-set",
        r"folder\golden-set",
        "golden-set.xlsx",
    ],
)
def test_resolve_workbook_rejects_unsafe_titles(tmp_path: Path, title: str):
    with pytest.raises(ValueError):
        resolve_workbook(title, root=tmp_path)


@pytest.mark.parametrize(
    ("headers", "values", "expected_id", "expected_qtype"),
    [
        (["순번", "질문", "모범답변", "질문유형"], [7, "질문 A", "정답 A", "단일검색"], "7", "단일검색"),
        ([" ID ", " Question ", " REFERENCE_ANSWER ", " Category "], ["eng-1", "Question A", "Answer A", "faq"], "eng-1", "faq"),
    ],
)
def test_load_golden_workbook_accepts_korean_and_english_header_aliases(
    tmp_path: Path,
    headers: list[object],
    values: list[object],
    expected_id: str,
    expected_qtype: str,
):
    path = _write_workbook(tmp_path / "aliases.xlsx", [headers, values])

    items = load_golden_workbook(path)

    assert len(items) == 1
    assert items[0].id == expected_id
    assert items[0].qtype == expected_qtype
    assert items[0].question == str(values[1])
    assert items[0].ground_truth == str(values[2])


def test_load_golden_workbook_uses_first_nonempty_row_and_skips_blank_rows(
    tmp_path: Path,
):
    path = _write_workbook(
        tmp_path / "blank-rows.xlsx",
        [
            [None, None, None],
            [" ", None, "  "],
            ["질문", "정답"],
            ["질문 A", "정답 A"],
            [None, None],
            ["  ", None],
            ["질문 B", "정답 B"],
        ],
        sheet="질문지",
    )

    items = load_golden_workbook(path)

    assert [item.id for item in items] == ["row-4", "row-7"]
    assert [item.qtype for item in items] == ["미분류", "미분류"]
    assert [item.row_number for item in items] == [4, 7]
    assert all(item.sheet == "질문지" for item in items)


@pytest.mark.parametrize("id_header", ["순번", "id", "번호", "문항번호"])
def test_load_golden_workbook_accepts_id_aliases(tmp_path: Path, id_header: str):
    path = _write_workbook(
        tmp_path / f"id-{id_header}.xlsx",
        [[id_header, "질문", "정답"], [23, "질문", "정답"]],
    )

    assert load_golden_workbook(path)[0].id == "23"


@pytest.mark.parametrize("qtype_header", ["유형", "질문유형", "qtype", "category"])
def test_load_golden_workbook_accepts_qtype_aliases(
    tmp_path: Path, qtype_header: str
):
    path = _write_workbook(
        tmp_path / f"qtype-{qtype_header}.xlsx",
        [["질문", "정답", qtype_header], ["질문", "정답", "비교"]],
    )

    assert load_golden_workbook(path)[0].qtype == "비교"


@pytest.mark.parametrize(
    ("headers", "missing_name"),
    [
        (["정답"], "질문"),
        (["질문"], "정답"),
    ],
)
def test_load_golden_workbook_rejects_missing_required_columns(
    tmp_path: Path, headers: list[object], missing_name: str
):
    path = _write_workbook(tmp_path / "missing-column.xlsx", [headers])

    with pytest.raises(ValueError) as error:
        load_golden_workbook(path)

    assert missing_name in str(error.value)


def test_load_golden_workbook_rejects_header_only_dataset(tmp_path: Path):
    path = _write_workbook(tmp_path / "header-only.xlsx", [["질문", "정답"]])

    with pytest.raises(ValueError, match="평가 문항"):
        load_golden_workbook(path)


@pytest.mark.parametrize(
    ("headers", "values", "missing_name"),
    [
        (["질문", "정답"], [None, "정답"], "질문"),
        (["question", "ground_truth"], ["Question", "   "], "정답"),
    ],
)
def test_load_golden_workbook_rejects_missing_required_values_with_row_number(
    tmp_path: Path,
    headers: list[object],
    values: list[object],
    missing_name: str,
):
    path = _write_workbook(tmp_path / "missing-value.xlsx", [headers, values])

    with pytest.raises(ValueError) as error:
        load_golden_workbook(path)

    message = str(error.value)
    assert missing_name in message
    assert "2" in message


def test_load_golden_workbook_rejects_duplicate_ids_with_both_row_numbers(
    tmp_path: Path,
):
    path = _write_workbook(
        tmp_path / "duplicate-ids.xlsx",
        [
            ["순번", "질문", "정답"],
            [1, "질문 A", "정답 A"],
            [1, "질문 B", "정답 B"],
        ],
    )

    with pytest.raises(ValueError) as error:
        load_golden_workbook(path)

    message = str(error.value)
    assert "ID" in message
    assert "2" in message
    assert "3" in message


def test_load_golden_workbook_rejects_duplicate_questions_with_both_row_numbers(
    tmp_path: Path,
):
    path = _write_workbook(
        tmp_path / "duplicate-questions.xlsx",
        [
            ["질문", "정답"],
            ["중복 질문", "정답 A"],
            ["중복 질문", "정답 B"],
        ],
    )

    with pytest.raises(ValueError) as error:
        load_golden_workbook(path)

    message = str(error.value)
    assert "질문" in message
    assert "2" in message
    assert "3" in message


def test_load_real_workbook():
    items = load_golden_workbook(REAL_WORKBOOK)

    assert len(items) == 16
    assert items[0].id == "1"
    assert items[0].qtype == "미분류"
    assert items[0].ground_truth.strip()
    assert items[0].sheet == "Sheet1"
    assert items[0].row_number == 2