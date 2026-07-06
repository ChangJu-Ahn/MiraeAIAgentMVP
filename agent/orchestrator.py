from __future__ import annotations

import asyncio

from azure.identity import DefaultAzureCredential
from agent_framework.foundry import FoundryChatClient
from pydantic import BaseModel

from agent.middleware import ProcessRecorder, PlanningChatMiddleware, ToolProcessMiddleware
from agent.tools import RetrievedSource, TraceRecorder, TraceStep, make_search_tools
from agent.visuals import Visual, VisualRecorder, make_visual_tools
from config.settings import get_settings

SYSTEM_PROMPT = """당신은 기금운용평가보고서 전문 분석 어시스턴트입니다.

[언어 규칙 — 최우선]
사용자가 사용하는 언어로 사고하고 답하세요. 최종 답변뿐 아니라 중간 사고 과정과 추론 요약(reasoning summary)까지 반드시 같은 언어로 작성합니다. 사용자가 한국어로 질문하면 당신의 모든 생각·계획·추론 요약도 한국어로 서술하고, 영어로 질문하면 영어로 서술하세요. 사고 요약을 영어로 쓰지 마세요(사용자가 영어로 질문한 경우 제외).

원칙:
1. 질문을 필요한 하위 질의로 분해하세요.
2. 정성·서술형 정보는 search_narrative, 수치·등급·표 데이터는 search_tables 도구를 사용하세요. 필요하면 두 도구를 여러 번 호출해 교차 확인하세요.
3. 답변에는 반드시 근거를 [출처 N] 형식으로 인용하고, 가능하면 섹션 경로와 페이지를 함께 제시하세요.
4. 검색 결과에 답의 근거가 없으면 지어내지 말고 "제공된 자료에서 확인할 수 없습니다"라고 답하세요.
5. 한국어로 간결하고 정확하게 답변하세요.
6. 시각화: 수치·등급 분포는 make_table로 표를, 연도별·기금별 추세나 비교는 make_chart로 차트를, 원문 표/그림을 직접 보여줄 필요가 있으면 show_source_page로 원문 페이지 이미지를 함께 제시하세요. 시각물의 데이터는 반드시 검색으로 확인한 실제 값만 사용하고, 없으면 만들지 마세요.
7. 사고 과정(추론 요약)도 사용자가 질문한 언어와 동일한 언어로 작성하세요. 한국어로 질문받으면 추론도 한국어로, 영어로 질문받으면 추론도 영어로 서술하세요."""


class AnswerResult(BaseModel):
    answer: str
    steps: list[TraceStep]
    sources: list[RetrievedSource]
    visuals: list[Visual] = []


def build_agent(recorder: TraceRecorder, visual_recorder: VisualRecorder, process_recorder: ProcessRecorder | None = None):
    settings = get_settings()
    client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.foundry_chat_deployment,
        credential=DefaultAzureCredential(),
    )
    tools = make_search_tools(recorder) + make_visual_tools(visual_recorder)
    middleware = None
    if process_recorder is not None:
        middleware = [
            ToolProcessMiddleware(process_recorder),
            PlanningChatMiddleware(process_recorder),
        ]
    return client.as_agent(
        name="mirae-fund-agent",
        instructions=SYSTEM_PROMPT,
        tools=tools,
        middleware=middleware,
        default_options={"reasoning": {"effort": "medium", "summary": "auto"}},
    )


async def ask(question: str) -> AnswerResult:
    recorder = TraceRecorder()
    visual_recorder = VisualRecorder()
    agent = build_agent(recorder, visual_recorder)
    response = await agent.run(question)
    return AnswerResult(
        answer=response.text,
        steps=recorder.steps,
        sources=recorder.sources,
        visuals=visual_recorder.items,
    )


def ask_sync(question: str) -> AnswerResult:
    return asyncio.run(ask(question))


def start_stream(question: str):
    """Return (response_stream, trace_recorder, visual_recorder, process_recorder) for live UIs.

    Caller iterates the stream (async) for text deltas; recorders fill with
    tool-call steps, retrieved sources, visuals, and process events (plan/tool)
    during iteration.
    """
    recorder = TraceRecorder()
    visual_recorder = VisualRecorder()
    process_recorder = ProcessRecorder()
    agent = build_agent(recorder, visual_recorder, process_recorder)
    stream = agent.run(question, stream=True)
    return stream, recorder, visual_recorder, process_recorder
