from agent.visuals import ChartVisual, TableVisual
from app.visual_bind import chart_to_figure, table_to_dataframe


def test_table_to_dataframe():
    v = TableVisual(title="t", columns=["등급", "개수"], rows=[["탁월", "3"], ["우수", "5"]])
    df = table_to_dataframe(v)
    assert list(df.columns) == ["등급", "개수"]
    assert df.shape == (2, 2)
    assert df.iloc[0, 0] == "탁월"


def test_chart_to_figure_line():
    v = ChartVisual(
        title="추세", chart_kind="line", x_label="연도", y_label="점수",
        x=["2023", "2024", "2025"], series=[{"name": "국민연금", "y": [80.0, 82.5, 85.0]}],
    )
    fig = chart_to_figure(v)
    assert fig.layout.title.text == "추세"
    assert len(fig.data) == 1
    assert list(fig.data[0].y) == [80.0, 82.5, 85.0]


def test_chart_to_figure_bar():
    v = ChartVisual(
        title="비교", chart_kind="bar", x_label="기금", y_label="점수",
        x=["A", "B"], series=[{"name": "점수", "y": [70.0, 90.0]}],
    )
    fig = chart_to_figure(v)
    assert len(fig.data) == 1
