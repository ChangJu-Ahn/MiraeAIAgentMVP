from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chainlit as cl

from agent.observability import setup_observability
from agent.orchestrator import start_stream
from agent.visuals import ChartVisual, ImageVisual, TableVisual
from app.formatting import format_citations
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
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                tmp.write(png)
                tmp.close()
                elements.append(
                    cl.Image(
                        path=tmp.name, name=v.title, display="inline", mime="image/png", size="large"
                    )
                )
            else:
                elements.append(cl.Image(path=v.path, name=v.title, display="inline", size="large"))
    return elements


@cl.on_message
async def on_message(message: cl.Message) -> None:
    stream, trace, visual, process = start_stream(message.content)

    answer_msg = cl.Message(content="")
    shown = 0

    async def flush_process() -> None:
        nonlocal shown
        while shown < len(process.events):
            e = process.events[shown]
            icon = "🧠" if e.kind == "plan" else "🔧"
            async with cl.Step(name=f"{icon} {e.title}", type=e.kind) as s:
                s.output = e.detail
            shown += 1

    # 계획(🧠)·도구 실행(🔧)을 진행되는 대로 표시하고, 답변을 토큰 단위로 스트리밍
    async for update in stream:
        await flush_process()
        if update.text:
            await answer_msg.stream_token(update.text)
    await flush_process()
    await answer_msg.update()

    # 시각물 바인딩 (표/차트/원문 이미지)
    elements = _visual_elements(visual.items)
    if elements:
        await cl.Message(content="📊 시각화", elements=elements).send()

    # 근거 출처 카드
    citations = format_citations(trace.sources)
    if citations:
        await cl.Message(content=citations).send()
