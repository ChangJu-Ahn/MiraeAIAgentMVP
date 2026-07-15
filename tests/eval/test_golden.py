from eval.golden import GOLDEN_QA, GoldenItem

VALID_TYPES = {"단일검색", "표데이터", "다년도", "다중문서교차", "종합요약", "원문부재"}


def test_golden_qa_nonempty_and_typed():
    assert len(GOLDEN_QA) >= 12
    assert all(isinstance(x, GoldenItem) for x in GOLDEN_QA)
    assert all(x.qtype in VALID_TYPES for x in GOLDEN_QA)
    assert all(x.question.strip() for x in GOLDEN_QA)


def test_legacy_golden_item_defaults_excel_fields():
    item = GoldenItem(id="legacy", question="기존 질문", qtype="단일검색")

    assert item.ground_truth is None
    assert item.sheet is None
    assert item.row_number is None


def test_all_six_types_present():
    types = {x.qtype for x in GOLDEN_QA}
    assert VALID_TYPES.issubset(types), f"missing types: {VALID_TYPES - types}"


def test_ids_unique():
    ids = [x.id for x in GOLDEN_QA]
    assert len(ids) == len(set(ids))


def test_has_hallucination_probes():
    assert sum(1 for x in GOLDEN_QA if x.qtype == "원문부재") >= 2
