from eval.golden import GoldenItem
from eval.report import build_report
from eval.runner import run_eval_sync


def test_runner_small_subset_produces_scored_rows():
    items = [
        GoldenItem(
            id="s1",
            question="자산운용 평가의 목적은?",
            qtype="단일검색",
            ground_truth="기금의 자산운용 성과와 운용체계를 평가해 효율성과 투명성을 높이고 개선을 유도하는 것이다.",
        ),
        GoldenItem(
            id="s2",
            question="2025회계연도 기금운용평가보고서에 아이폰 판매량 정보가 있나요?",
            qtype="원문부재",
            ground_truth="2025회계연도 기금운용평가보고서에는 아이폰 판매량 정보가 없다.",
        ),
    ]
    rows = run_eval_sync(items)
    assert len(rows) == 2
    expected_metrics = {"groundedness", "relevance", "similarity", "coherence", "fluency"}
    for row in rows:
        assert set(row.metrics) == expected_metrics
        assert set(row.reasons) == expected_metrics
        assert all(row.reasons.values())
    halluc_row = next(r for r in rows if r.qtype == "원문부재")
    assert halluc_row.refused is True
    md = build_report(rows)
    assert "평가 리포트" in md
