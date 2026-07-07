from agent.followups import _parse_questions


def test_parse_questions_json_array():
    text = '["수익률은 어떻게 되나요?", "위험 등급은?", "비교 기금은?"]'
    assert _parse_questions(text, 3) == [
        "수익률은 어떻게 되나요?",
        "위험 등급은?",
        "비교 기금은?",
    ]


def test_parse_questions_json_in_code_fence():
    text = '```json\n["A?", "B?"]\n```'
    assert _parse_questions(text, 3) == ["A?", "B?"]


def test_parse_questions_limits_to_n():
    text = '["a?", "b?", "c?", "d?"]'
    assert _parse_questions(text, 2) == ["a?", "b?"]


def test_parse_questions_line_fallback():
    text = "1. 첫 번째 질문?\n2. 두 번째 질문?"
    out = _parse_questions(text, 3)
    assert out == ["첫 번째 질문?", "두 번째 질문?"]


def test_parse_questions_empty():
    assert _parse_questions("", 3) == []
