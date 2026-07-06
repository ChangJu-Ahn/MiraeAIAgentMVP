from eval.golden import GoldenItem
from eval.report import build_report
from eval.runner import run_eval_sync


def test_runner_small_subset_produces_scored_rows():
    items = [
        GoldenItem(id="s1", question="자산운용 평가의 목적은?", qtype="단일검색"),
        GoldenItem(id="s2", question="이 보고서에 나온 아이폰 판매량은?", qtype="원문부재"),
    ]
    rows = run_eval_sync(items)
    assert len(rows) == 2
    grounded_row = next(r for r in rows if r.qtype == "단일검색")
    assert grounded_row.metrics.get("groundedness", 0) > 0
    halluc_row = next(r for r in rows if r.qtype == "원문부재")
    assert halluc_row.refused is True
    md = build_report(rows)
    assert "평가 리포트" in md
