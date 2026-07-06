from __future__ import annotations

import json
from typing import Callable, Literal, Union

from pydantic import BaseModel


class TableVisual(BaseModel):
    kind: Literal["table"] = "table"
    title: str
    columns: list[str]
    rows: list[list[str]]


class ChartVisual(BaseModel):
    kind: Literal["chart"] = "chart"
    title: str
    chart_kind: str  # "line" | "bar"
    x_label: str
    y_label: str
    x: list[str]
    series: list[dict]  # {"name": str, "y": list[float]}


class ImageVisual(BaseModel):
    kind: Literal["image"] = "image"
    title: str
    path: str


Visual = Union[TableVisual, ChartVisual, ImageVisual]


class VisualRecorder(BaseModel):
    items: list[Visual] = []


def make_visual_tools(recorder: VisualRecorder) -> list[Callable[..., str]]:
    def make_table(title: str, columns_json: str, rows_json: str) -> str:
        """표(정형 데이터)를 사용자 화면에 표시합니다. 검색으로 확인한 실제 값만 사용하세요.

        Args:
            title: 표 제목.
            columns_json: 열 이름 배열의 JSON 문자열. 예: '["등급","개수"]'
            rows_json: 행 배열의 JSON 문자열(각 행은 문자열 배열). 예: '[["탁월","3"],["우수","5"]]'
        """
        columns = json.loads(columns_json)
        rows = json.loads(rows_json)
        recorder.items.append(TableVisual(title=title, columns=columns, rows=rows))
        return f"표 '{title}' 표시함 ({len(rows)}행)"

    def make_chart(
        title: str, chart_kind: str, x_label: str, y_label: str, x_json: str, series_json: str
    ) -> str:
        """차트(추세/비교)를 사용자 화면에 표시합니다. 검색으로 확인한 실제 수치만 사용하세요.

        Args:
            title: 차트 제목.
            chart_kind: 'line' 또는 'bar'.
            x_label: x축 이름.
            y_label: y축 이름.
            x_json: x축 값 배열의 JSON 문자열. 예: '["2023","2024","2025"]'
            series_json: 시리즈 배열의 JSON 문자열. 각 항목 {"name":str,"y":[숫자...]}.
        """
        x = json.loads(x_json)
        series = json.loads(series_json)
        recorder.items.append(
            ChartVisual(
                title=title,
                chart_kind=chart_kind if chart_kind in ("line", "bar") else "bar",
                x_label=x_label,
                y_label=y_label,
                x=x,
                series=series,
            )
        )
        return f"차트 '{title}' 표시함"

    def show_source_page(page: int) -> str:
        """인용 근거의 원문 PDF 페이지를 이미지로 사용자에게 보여줍니다.

        Args:
            page: 표시할 물리 페이지 번호(검색 결과의 page 값).
        """
        recorder.items.append(ImageVisual(title=f"원문 {page}페이지", path=f"__page__:{page}"))
        return f"원문 {page}페이지 이미지 표시함"

    return [make_table, make_chart, show_source_page]
