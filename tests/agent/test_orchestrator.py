from agent.orchestrator import ask_sync


def test_grounded_answer_cites_and_uses_tools():
    r = ask_sync("자산운용 평가의 목적은 무엇인가요?")
    assert r.answer.strip()
    assert r.steps, "expected at least one tool call (agentic retrieval)"
    assert r.sources, "expected retrieved sources"
    assert "[출처" in r.answer, f"expected grounded citation in answer, got: {r.answer}"


def test_hallucination_guard_refuses_unknown():
    r = ask_sync("2025년 애플 아이폰 판매량은 이 보고서에 얼마로 나오나요?")
    # The corpus is Korean fund-evaluation reports; an iPhone sales figure is out of
    # corpus. The guard must REFUSE (state absence), never fabricate a number.
    # A fabricated declarative answer ("판매량은 2억 대입니다") contains no negation
    # marker, so requiring one still catches fabrication while tolerating phrasing variety.
    negation_markers = [
        "없습니다",
        "없음",
        "않습니다",
        "않았습니다",
        "확인할 수 없",
        "확인되지 않",
        "제공되지 않",
        "포함되어 있지 않",
        "나와 있지 않",
        "찾을 수 없",
    ]
    assert any(m in r.answer for m in negation_markers), f"Expected refusal, got: {r.answer}"
