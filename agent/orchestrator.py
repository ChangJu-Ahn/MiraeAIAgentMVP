from __future__ import annotations

import asyncio
from datetime import date
import re

from azure.identity import DefaultAzureCredential
from agent_framework import AgentSession
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
7. 오늘은 {today}이다. 질문에 연도·문서유형(보고서=report/지침=guideline)·기금명·기금규모(대형중소형/대규모)가 명시되면 검색 도구의 해당 필터 인자를 채워라. 연도를 지정하지 않으면 현재 시점 기준 가장 최신 회계연도 보고서를 기본으로 조회하라. '작년/최근' 등 상대 표현은 오늘 날짜 기준으로 해석하라. 여러 연도를 비교하는 질문이면 연도별로 각각 검색하라. fund_name/fund_scale 필터로 0건이면 해당 필터를 빼고 재검색하라.

[구조화 도구 라우팅 규칙]
8. 질문에 '전체', '각 기금', '상위', '하위', '순위', '가장' 등 전체 모집단 의도가 포함되면 반드시 구조화 카탈로그·집계 도구(list_funds, resolve_fund, get_fund_evaluations, aggregate_evaluations, fund_analytics)를 먼저 사용하라.
9. 개별 기금의 정성적 질문은 resolve_fund로 엔티티를 확인한 뒤 search_narrative/search_tables로 심층 검색하라.
10. resolve_fund가 0건이면 같은 연도의 list_funds로 전체 TOC를 확인하고 그 catalog [출처]를 인용하라. 이름과 별칭이 목록에 모두 없으면 '평가 대상 기금이 아니다'라고 답하고, search_narrative/search_tables 같은 시맨틱 검색으로 부재를 재확인하지 마라.
11. '가감점'·'조정'·'가점'·'감점' 항목과 점수 질문은 get_fund_evaluations(fund_name=..., year=..., metric='가감점')을 먼저 사용하라. 반환된 adjustment 항목과 부호 있는 점수를 그대로 답하고, 시맨틱 검색 결과로 없다고 결론내리지 마라.
12. 특정 연도 전체 평가결과를 총평하라는 질문은 fund_analytics(operation='distribution', years=[연도], metric='overall_grade', population='evaluated')와 fund_analytics(operation='rank', years=[연도], metric='asset_management_performance', population='evaluated', order='desc', limit=100)를 모두 사용하라. 모집단 수, 등급별 수와 기금명, 최상·최하 종합등급, 계량 상·하위 점수와 순위를 구조화 결과로 요약하라.
13. 수치 정렬·등급 순위·등급 분포·연도별 증감·다년 교집합을 반복적 시맨틱 top-k 검색이나 LLM의 직접 계산으로 만들지 마라. 순위는 fund_analytics(operation='rank'), 분포는 'distribution', 연도 비교는 'compare_years', 상승·하락은 'grade_changes', 동일 등급 유지는 'maintained_grade'를 사용하라.
14. '최종등급'·'종합등급'은 annual summary 기반 overall_grade, '자산운용 성과점수'·'계량점수(50점 만점)'는 asset_management_performance, '비계량 합계'는 qualitative_total로 구분하라. 지표값(metric_value)과 평가점수(score)를 혼동하지 마라.
15. 최종등급을 받은 기금 중 특정 기금의 계량 성과 순위나 '몇 위'를 묻거나, 최저·최고 종합등급 기금과 계량 성과를 함께 묻는 결합 질문은 fund_analytics(operation='rank', metric='asset_management_performance', population='evaluated', order='desc', limit=100)를 사용하라. 이 순위의 모집단은 annual overall_grade가 있는 fund ID와 계량 성과 fact의 교집합이며, LLM이 직접 순위를 세지 마라. 답변에는 해당 기금의 계량 성과 점수와 순위(N개 중 M위)를 모두 명시하고, 질문하지 않은 계량 성과 자체의 세부등급은 덧붙이지 마라.
16. 전년도에 지적받은 지적사항이 다음 연도에 개선됐는지 묻는 질문은 먼저 전년도에서 '미흡점·개선방안·권고'를 검색해 지적사항을 열거하라. 다음 연도에는 각 지적사항의 동일한 주제어(규정, 위원 겸직, 참석률, 단기자금 등)로 각각 검색하고, 항목별로 개선·미개선·부분개선을 판정해 두 연도의 근거를 함께 인용하라. 위원회 문제가 나오면 위원 겸직과 참석률은 별개 항목으로 검색하고 판정하라. 두 연도에 대한 '위원 겸직'과 '참석률'의 별도 검색을 모두 완료하기 전에는 답하지 마라. 최종 답변에는 검색한 모든 지적사항을 한 항목씩 유지하고 참석률 판정을 반드시 포함하라. 다른 수치 항목으로 대체하지 마라.
17. 집계 결과의 모집단 기준, TOC 기금 수, 실제 비교 기금 수, 제외·누락 기금을 반드시 공개하라. 부분 결과를 전체인 것처럼 제시하지 마라.
18. 구조화 팩트 출처는 [출처 N] 형식으로 인용하라. 동일 source_chunk_id는 중복 기록하지 않는다.
19. corpus manifest가 요청한 연도·문서유형의 부재를 알리면 그 판단을 권위 있는 출처로 사용하라. 연도·문서유형 필터를 제거하지 마라. 다른 연도나 문서유형으로 대체하지 마라. 존재하는 요청 연도의 결과만 답하고 누락 연도는 '제공된 자료에서 확인할 수 없음'으로 명시하라."""


_YEAR_RANGE_RE = re.compile(
    r"(?<!\d)(20\d{2})(?:\s*[~～\-–—]\s*(20\d{2}))?(?!\d)"
)


def _request_context(question: str) -> tuple[list[int], str | None]:
    years: set[int] = set()
    for match in _YEAR_RANGE_RE.finditer(question):
        start = int(match.group(1))
        end_text = match.group(2)
        if end_text is None:
            years.add(start)
            continue
        end = int(end_text)
        if start <= end and end - start <= 20:
            years.update(range(start, end + 1))
        else:
            years.update((start, end))

    if "지침" in question:
        doc_type = "guideline"
    elif years:
        doc_type = "report"
    else:
        doc_type = None
    return sorted(years), doc_type


class AnswerResult(BaseModel):
    answer: str
    steps: list[TraceStep]
    sources: list[RetrievedSource]
    evidence: list[str] = []
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
    requested_years, requested_doc_type = _request_context(question)
    recorder = TraceRecorder(
        requested_years=requested_years,
        requested_doc_type=requested_doc_type,
    )
    visual_recorder = VisualRecorder()
    agent = build_agent(recorder, visual_recorder)
    response = await agent.run(question)
    return AnswerResult(
        answer=response.text,
        steps=recorder.steps,
        sources=recorder.sources,
        evidence=recorder.evidence,
        visuals=visual_recorder.items,
    )


def ask_sync(question: str) -> AnswerResult:
    return asyncio.run(ask(question))


def new_session() -> AgentSession:
    """새 대화 세션을 만든다. 채팅창(대화)당 1개를 만들어 매 턴 재사용한다.

    Foundry가 대화 이력을 서버측에 저장(STORES_BY_DEFAULT)하므로, 이 세션 객체를
    매 run에 넘기면 첫 응답 후 service_session_id가 채워지고 이후 턴이 이어진다.
    """
    return AgentSession()


def start_stream(question: str, effort: str = "medium", session: AgentSession | None = None):
    """Return (response_stream, trace_recorder, visual_recorder) for live UIs.

    Caller iterates the stream (async) for text/reasoning/tool deltas; recorders
    fill with tool-call steps, retrieved sources, and visuals during iteration.
    effort는 추론 강도(low/medium/high).
    session을 넘기면 이전 턴들의 대화 이력을 이어받아 멀티턴으로 동작한다(None이면 단발).
    """
    requested_years, requested_doc_type = _request_context(question)
    recorder = TraceRecorder(
        requested_years=requested_years,
        requested_doc_type=requested_doc_type,
    )
    visual_recorder = VisualRecorder()
    agent = build_agent(recorder, visual_recorder, effort)
    stream = agent.run(question, session=session, stream=True)
    return stream, recorder, visual_recorder
