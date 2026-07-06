from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chainlit as cl

from agent.orchestrator import ask
from agent.visuals import ChartVisual, ImageVisual, TableVisual
from app.formatting import format_citations, format_reasoning_step
from app.visual_bind import chart_to_figure, table_to_dataframe
from config.settings import get_settings
from ingest.figures import render_page_png


@cl.on_chat_start
async def on_chat_start() -> None:
    await cl.Message(
        content="안녕하세요! 기금운용평가보고서 기반 AI 어시스턴트입니다. 질문을 입력해 주세요."
    ).send()


def _visual_elements(visuals: list) -> list:
    elements: list = []
    for v in visuals:
        if isinstance(v, TableVisual):
            elements.append(
                cl.Dataframe(data=table_to_dataframe(v), name=v.title, display="inline")
            )
        elif isinstance(v, ChartVisual):
            elements.append(
                cl.Plotly(figure=chart_to_figure(v), name=v.title, display="inline")
            )
        elif isinstance(v, ImageVisual):
            if v.path.startswith("__page__:"):
                page = int(v.path.split(":", 1)[1])
                png = render_page_png(get_settings().source_pdf_path, page)
                elements.append(cl.Image(content=png, name=v.title, display="inline"))
            else:
                elements.append(cl.Image(path=v.path, name=v.title, display="inline"))
    return elements


@cl.on_message
async def on_message(message: cl.Message) -> None:
    result = await ask(message.content)

    # 관측 가능한 추론: 각 도구 호출을 단계로 표시
    for step in result.steps:
        async with cl.Step(name=step.tool, type="tool") as s:
            s.input = step.query
            s.output = format_reasoning_step(step)

    # 답변 (마크다운 표 네이티브 렌더)
    await cl.Message(content=result.answer).send()

    # 시각물 바인딩 (표/차트/원문 이미지)
    elements = _visual_elements(result.visuals)
    if elements:
        await cl.Message(content="📊 시각화", elements=elements).send()

    # 근거 출처 카드
    citations = format_citations(result.sources)
    if citations:
        await cl.Message(content=citations).send()
