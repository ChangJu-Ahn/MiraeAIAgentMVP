from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chainlit as cl

from agent.observability import setup_observability
from agent.orchestrator import start_stream
from agent.visuals import ChartVisual, ImageVisual, TableVisual
from app.formatting import format_citations, format_reasoning_step
from app.visual_bind import chart_to_figure, table_to_dataframe
from config.settings import get_settings
from ingest.figures import render_page_png

setup_observability()


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
    stream, trace, visual = start_stream(message.content)

    answer_msg = cl.Message(content="")
    shown_steps = 0

    async def flush_steps() -> None:
        nonlocal shown_steps
        while shown_steps < len(trace.steps):
            st = trace.steps[shown_steps]
            async with cl.Step(name=st.tool, type="tool") as s:
                s.input = st.query
                s.output = format_reasoning_step(st)
            shown_steps += 1

    # 도구 호출(추론 단계)을 진행되는 대로 표시하고, 답변을 토큰 단위로 스트리밍
    async for update in stream:
        await flush_steps()
        if update.text:
            await answer_msg.stream_token(update.text)
    await flush_steps()
    await answer_msg.update()

    # 시각물 바인딩 (표/차트/원문 이미지)
    elements = _visual_elements(visual.items)
    if elements:
        await cl.Message(content="📊 시각화", elements=elements).send()

    # 근거 출처 카드
    citations = format_citations(trace.sources)
    if citations:
        await cl.Message(content=citations).send()
