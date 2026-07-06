from agent.orchestrator import ask_sync


def test_grounded_answer_cites_and_uses_tools():
    r = ask_sync("자산운용 평가의 목적은 무엇인가요?")
    assert r.answer.strip()
    assert r.steps, "expected at least one tool call (agentic retrieval)"
    assert r.sources, "expected retrieved sources"


def test_hallucination_guard_refuses_unknown():
    r = ask_sync("2025년 애플 아이폰 판매량은 이 보고서에 얼마로 나오나요?")
    # Must refuse, not fabricate a number - accept various refusal phrasings
    refusal_patterns = ["확인할 수 없습니다", "없습니다", "포함되어 있지 않습니다", "확인되지 않았습니다"]
    assert any(pattern in r.answer for pattern in refusal_patterns), f"Expected refusal, got: {r.answer}"
