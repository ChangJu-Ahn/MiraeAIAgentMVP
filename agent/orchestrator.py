from __future__ import annotations

import asyncio
from datetime import date

from azure.identity import DefaultAzureCredential
from agent_framework.foundry import FoundryChatClient
from pydantic import BaseModel

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
5. 사용자가 질문한 언어로 간결하고 정확하게 답변하세요.
6. 시각화는 기본적으로 만들지 마세요(답변은 글과 [출처] 인용만으로 충분합니다). 다음 두 경우에만 사용하세요: (a) 사용자가 표·차트·원문 페이지 등 시각물을 명시적으로 요청했을 때, (b) 여러 수치·등급을 비교해 표/차트가 글보다 확실히 이해에 도움이 될 때. 이때 수치·등급 분포는 make_table, 연도별·기금별 추세·비교는 make_chart를 쓰세요. show_source_page(원문 페이지 이미지)는 사용자가 "원문을 직접 보여달라"고 요청한 경우에만 사용하세요. 시각물의 데이터는 반드시 검색으로 확인한 실제 값만 사용하고, 없으면 만들지 마세요.
7. 오늘은 {today}이다. 질문에 연도·문서유형(보고서=report/지침=guideline)·기금명·기금규모(대형중소형/대규모)가 명시되면 검색 도구의 해당 필터 인자를 채워라. 연도를 지정하지 않으면 현재 시점 기준 가장 최신 회계연도 보고서를 기본으로 조회하라. '작년/최근' 등 상대 표현은 오늘 날짜 기준으로 해석하라. 여러 연도를 비교하는 질문이면 연도별로 각각 검색하라. fund_name/fund_scale 필터로 0건이면 해당 필터를 빼고 재검색하라."""


class AnswerResult(BaseModel):
    answer: str
    steps: list[TraceStep]
    sources: list[RetrievedSource]
    visuals: list[Visual] = []


VALID_EFFORTS = ("low", "medium", "high")


def _reasoning_options(effort: str = "medium") -> dict:
    """추론 강도(effort)로 Foundry reasoning 옵션을 만든다. 잘못된 값은 medium으로 대체."""
    if effort not in VALID_EFFORTS:
        effort = "medium"
    return {"reasoning": {"effort": effort, "summary": "auto"}}


def build_agent(
    recorder: TraceRecorder, visual_recorder: VisualRecorder, effort: str = "medium"
):
    settings = get_settings()
    client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.foundry_chat_deployment,
        credential=DefaultAzureCredential(),
    )
    tools = make_search_tools(recorder) + make_visual_tools(visual_recorder)
    instructions = SYSTEM_PROMPT.replace("{today}", date.today().isoformat())
    return client.as_agent(
        name="mirae-fund-agent",
        instructions=instructions,
        tools=tools,
        default_options=_reasoning_options(effort),
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


def start_stream(question: str, effort: str = "medium"):
    """Return (response_stream, trace_recorder, visual_recorder) for live UIs.

    Caller iterates the stream (async) for text/reasoning/tool deltas; recorders
    fill with tool-call steps, retrieved sources, and visuals during iteration.
    effort는 추론 강도(low/medium/high).
    """
    recorder = TraceRecorder()
    visual_recorder = VisualRecorder()
    agent = build_agent(recorder, visual_recorder, effort)
    stream = agent.run(question, stream=True)
    return stream, recorder, visual_recorder
