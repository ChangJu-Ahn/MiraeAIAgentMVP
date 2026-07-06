from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from agent.visuals import ChartVisual, TableVisual


def table_to_dataframe(v: TableVisual) -> pd.DataFrame:
    return pd.DataFrame(v.rows, columns=v.columns)


def chart_to_figure(v: ChartVisual) -> go.Figure:
    fig = go.Figure()
    for s in v.series:
        name = s.get("name", "")
        y = s.get("y", [])
        if v.chart_kind == "bar":
            fig.add_trace(go.Bar(name=name, x=v.x, y=y))
        else:
            fig.add_trace(go.Scatter(name=name, x=v.x, y=y, mode="lines+markers"))
    fig.update_layout(title=v.title, xaxis_title=v.x_label, yaxis_title=v.y_label)
    return fig
