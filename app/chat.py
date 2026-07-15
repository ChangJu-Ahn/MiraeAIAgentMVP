from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chainlit as cl

from agent.observability import setup_observability
from agent.orchestrator import new_session, start_stream
from agent.tools import TraceRecorder
from agent.visuals import ChartVisual, ImageVisual, TableVisual, VisualRecorder
from app.formatting import cited_sources, dedup_sources, format_citations
from app.visual_bind import chart_to_figure, table_to_dataframe
from config.settings import get_settings
from ingest.figures import render_page_png

setup_observability()


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("agent_session", new_session())
    await cl.Message(
        content="안녕하세요. 기금운용평가보고서에 대해 질문해 주세요."
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
                try:
                    page = int(v.path.split(":", 1)[1])
                    pdf = _resolve_source_pdf(get_settings().source_pdf_path)
                    if not pdf:
                        continue
                    png = render_page_png(pdf, page)
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                    tmp.write(png)
                    tmp.close()
                    elements.append(
                        cl.Image(
                            path=tmp.name,
                            name=v.title,
                            display="inline",
                            mime="image/png",
                            size="large",
                        )
                    )
                except Exception:  # noqa: BLE001 - 원문 페이지 렌더 실패는 건너뜀
                    continue
            else:
                elements.append(cl.Image(path=v.path, name=v.title, display="inline", size="large"))
    return elements


def _resolve_source_pdf(configured: str) -> str | None:
    """원문 PDF 경로를 견고하게 해석. 정확 경로가 없으면 docs/에서 2025 보고서를 찾는다.

    (대소문자·유니코드 정규화 차이로 정확 경로가 안 맞을 수 있어 목록 조회로 보완)
    """
    import os
    import unicodedata

    if os.path.exists(configured):
        return configured
    for d in ("docs", "Docs"):
        if os.path.isdir(d):
            for f in os.listdir(d):
                nf = unicodedata.normalize("NFC", f)
                if f.lower().endswith(".pdf") and "2025" in nf and "보고서" in nf:
                    return os.path.join(d, f)
    return None


async def _stream_answer(
    question: str,
) -> tuple[str, TraceRecorder, VisualRecorder]:
    session = cl.user_session.get("agent_session")
    stream, trace, visual = start_stream(question, session=session)
    message = cl.Message(content="")
    answer_text = ""
    async for update in stream:
        for content in update.contents:
            if getattr(content, "type", None) != "text":
                continue
            token = getattr(content, "text", "") or ""
            if token:
                answer_text += token
                await message.stream_token(token)

    await message.update()
    return answer_text, trace, visual


@cl.on_message
async def on_message(message: cl.Message) -> None:
    answer_text, trace, visual = await _stream_answer(message.content)

    elements = _visual_elements(visual.items)
    if elements:
        await cl.Message(content="📊 시각화", elements=elements).send()

    used = cited_sources(answer_text, trace.sources)
    sources = used or dedup_sources(trace.sources)
    heading = "근거" if used else "참고한 자료"
    citations = format_citations(sources, heading=heading)
    if citations:
        await cl.Message(content=citations).send()
