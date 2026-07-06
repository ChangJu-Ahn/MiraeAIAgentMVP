from __future__ import annotations

import re

from functools import lru_cache

from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

from config.settings import get_settings

_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_lang(text: str) -> str:
    """아주 단순한 언어 감지: 한글이 라틴 문자보다 많으면 'ko', 아니면 'en'."""
    ko = len(_HANGUL.findall(text))
    en = len(_LATIN.findall(text))
    return "ko" if ko >= en else "en"


def needs_translation(segment: str, target: str) -> bool:
    """세그먼트가 이미 목표 언어면 번역 불필요."""
    seg = segment.strip()
    if not seg:
        return False
    return detect_lang(seg) != target


@lru_cache(maxsize=None)
def _translator(lang_name: str):
    """목표 언어별 번역 에이전트를 한 번만 생성해 재사용한다."""
    s = get_settings()
    client = FoundryChatClient(
        project_endpoint=s.foundry_project_endpoint,
        model=s.foundry_eval_deployment,
        credential=DefaultAzureCredential(),
    )
    return client.as_agent(
        name="reasoning-translator",
        instructions=(
            f"You are a translator. Translate the user's text into {lang_name}, "
            "preserving markdown formatting (e.g. **bold**), tone, and meaning. "
            "Output only the translation, nothing else."
        ),
    )


async def translate(text: str, target: str) -> str:
    """추론 요약 등 짧은 텍스트를 목표 언어로 번역. 실패 시 원문 반환."""
    lang_name = {"ko": "한국어", "en": "English"}.get(target, target)
    try:
        resp = await _translator(lang_name).run(text)
        out = (resp.text or "").strip()
        return out or text
    except Exception:  # noqa: BLE001
        return text
