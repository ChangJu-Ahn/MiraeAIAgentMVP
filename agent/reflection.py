from __future__ import annotations

import json
import re

from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential
from pydantic import BaseModel

from config.settings import get_settings


class ReflectionVerdict(BaseModel):
    sufficient: bool
    missing: str = ""


_CRITIQUE_PROMPT = """당신은 답변 품질 점검자입니다. 아래 질문과 답변, 검색 근거를 보고
답변이 질문을 충분히·근거 기반으로 커버했는지 판정하세요.
누락된 하위 질문·수치·근거가 있으면 부족으로 판정하고 무엇이 부족한지 한국어로 구체적으로 쓰세요.
반드시 JSON만 출력: {{"sufficient": true/false, "missing": "부족한 점(없으면 빈 문자열)"}}

[질문]
{question}

[답변]
{answer}

[검색 근거 요약]
{sources}
"""


def augmented_question(question: str, missing: str) -> str:
    return (
        f"{question}\n\n"
        f"[보완 지시] 이전 답변에서 다음이 부족했습니다. 추가로 검색·조회하여 반드시 보완해 답하세요: {missing}"
    )


def parse_verdict(text: str) -> ReflectionVerdict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return ReflectionVerdict(sufficient=True)
    try:
        data = json.loads(match.group(0))
        return ReflectionVerdict(
            sufficient=bool(data.get("sufficient", True)),
            missing=str(data.get("missing", "")),
        )
    except (ValueError, TypeError):
        return ReflectionVerdict(sufficient=True)


async def critique(
    question: str, answer: str, sources: list
) -> ReflectionVerdict:
    settings = get_settings()
    client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.foundry_eval_deployment,
        credential=DefaultAzureCredential(),
    )
    agent = client.as_agent(
        name="reflection-critic",
        instructions="You output only JSON.",
    )
    source_summary = (
        "\n".join(
            f"[출처 {getattr(source, 'n', '?')}] {getattr(source, 'section_path', '')}"
            for source in sources[:10]
        )
        or "(없음)"
    )
    prompt = _CRITIQUE_PROMPT.format(
        question=question,
        answer=answer,
        sources=source_summary,
    )
    response = await agent.run(prompt)
    return parse_verdict(response.text)