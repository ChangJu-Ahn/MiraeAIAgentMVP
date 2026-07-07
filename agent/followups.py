from __future__ import annotations

import json
import re
from functools import lru_cache

from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

from config.settings import get_settings

_INSTRUCTIONS = (
    "당신은 사용자가 방금 받은 답변에 이어서 궁금해할 만한 후속 질문을 제안합니다. "
    "질문은 사용자가 사용한 언어로, 짧고 구체적으로 작성하세요. "
    "반드시 질문 문자열만 담은 JSON 배열 하나만 출력하고, 그 외 텍스트는 절대 쓰지 마세요. "
    '예: ["질문 1?", "질문 2?", "질문 3?"]'
)


@lru_cache(maxsize=1)
def _agent():
    """후속 질문 생성 에이전트를 한 번만 만들어 재사용한다."""
    s = get_settings()
    client = FoundryChatClient(
        project_endpoint=s.foundry_project_endpoint,
        model=s.foundry_chat_deployment,
        credential=DefaultAzureCredential(),
    )
    return client.as_agent(name="followup-suggester", instructions=_INSTRUCTIONS)


def _parse_questions(text: str, n: int) -> list[str]:
    """모델 출력에서 질문 문자열 리스트를 추출. JSON 배열 우선, 실패 시 줄 단위 폴백."""
    text = (text or "").strip()
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            arr = json.loads(m.group(0))
            qs = [str(x).strip() for x in arr if str(x).strip()]
            if qs:
                return qs[:n]
        except (ValueError, TypeError):
            pass
    lines = [re.sub(r"^[\-\*\d\.\)\s]+", "", ln).strip() for ln in text.splitlines()]
    qs = [ln for ln in lines if len(ln) >= 5]
    return qs[:n]


async def suggest_followups(question: str, answer: str, n: int = 3) -> list[str]:
    """원 질문과 답변을 바탕으로 관련 후속 질문 n개를 제안. 실패 시 빈 리스트."""
    prompt = f"[원 질문]\n{question}\n\n[답변]\n{answer}\n\n위 대화에 이어질 후속 질문 {n}개를 제안하세요."
    try:
        resp = await _agent().run(prompt)
        return _parse_questions(resp.text or "", n)
    except Exception:  # noqa: BLE001
        return []
