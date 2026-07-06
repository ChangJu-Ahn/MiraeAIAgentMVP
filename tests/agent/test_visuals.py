import json

from agent.visuals import ChartVisual, TableVisual, VisualRecorder, make_visual_tools


def test_make_table_records_table_visual():
    rec = VisualRecorder()
    make_table, _chart, _page = make_visual_tools(rec)
    out = make_table(
        title="등급 분포",
        columns_json=json.dumps(["등급", "개수"], ensure_ascii=False),
        rows_json=json.dumps([["탁월", "3"], ["우수", "5"]], ensure_ascii=False),
    )
    assert "등급 분포" in out
    assert len(rec.items) == 1
    v = rec.items[0]
    assert isinstance(v, TableVisual)
    assert v.columns == ["등급", "개수"]
    assert v.rows[0] == ["탁월", "3"]


def test_make_chart_records_chart_visual():
    rec = VisualRecorder()
    _table, make_chart, _page = make_visual_tools(rec)
    make_chart(
        title="등급 추세",
        chart_kind="line",
        x_label="연도",
        y_label="점수",
        x_json=json.dumps(["2023", "2024", "2025"]),
        series_json=json.dumps([{"name": "국민연금", "y": [80.0, 82.5, 85.0]}], ensure_ascii=False),
    )
    assert len(rec.items) == 1
    v = rec.items[0]
    assert isinstance(v, ChartVisual)
    assert v.chart_kind == "line"
    assert v.series[0]["name"] == "국민연금"


def test_show_source_page_records_image_marker():
    rec = VisualRecorder()
    _t, _c, show_source_page = make_visual_tools(rec)
    show_source_page(241)
    assert len(rec.items) == 1
    assert rec.items[0].kind == "image"
    assert rec.items[0].path == "__page__:241"
