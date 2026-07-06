from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chainlit as cl

from agent.orchestrator import ask
from app.formatting import format_citations


@cl.on_chat_start
async def on_chat_start() -> None:
    await cl.Message(
        content="안녕하세요! 기금운용평가보고서 기반 AI 어시스턴트입니다. 질문을 입력해 주세요."
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    result = await ask(message.content)

    # 관측 가능한 추론: 각 도구 호출을 단계로 표시
    for step in result.steps:
        async with cl.Step(name=step.tool, type="tool") as s:
            s.input = step.query
            s.output = f"{step.n_hits}건 검색"

    # 답변 (마크다운 표 네이티브 렌더)
    await cl.Message(content=result.answer).send()

    # 근거 출처 카드
    citations = format_citations(result.sources)
    if citations:
        await cl.Message(content=citations).send()
