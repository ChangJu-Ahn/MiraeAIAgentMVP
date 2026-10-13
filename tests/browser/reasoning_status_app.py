"""Deterministic Chainlit UI fixture; no model or Azure calls."""

import asyncio

import chainlit as cl


@cl.on_message
async def on_message(message: cl.Message) -> None:
    async with cl.Step(name="생각 중", type="reasoning") as reasoning:
        await asyncio.sleep(2)
        await reasoning.stream_token("검색 근거를 확인합니다.")
        async with cl.Step(name="🔧 search_tables", type="tool", parent_id=reasoning.id) as tool:
            tool.input = "평가점수"
            await asyncio.sleep(4)
            tool.output = "검색 결과 1건"
        reasoning.name = "생각 중 (총 2.0s)"
        await reasoning.update()
    await cl.Message(content="상태 표시 확인 완료").send()
