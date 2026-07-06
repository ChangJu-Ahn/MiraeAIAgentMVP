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
