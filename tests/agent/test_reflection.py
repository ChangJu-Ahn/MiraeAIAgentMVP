from agent.reflection import ReflectionVerdict, augmented_question, parse_verdict


def test_augmented_question_includes_missing():
    question = augmented_question("탁월 등급이란?", "우수 등급과의 점수 구간 차이")
    assert "탁월 등급이란?" in question
    assert "우수 등급과의 점수 구간 차이" in question


def test_parse_verdict_json():
    verdict = parse_verdict('{"sufficient": false, "missing": "연도별 수치"}')
    assert verdict.sufficient is False
    assert "연도별" in verdict.missing


def test_parse_verdict_embedded_and_fallback():
    verdict = parse_verdict(
        '점검 결과: {"sufficient": true, "missing": ""} 입니다'
    )
    assert verdict.sufficient is True
    assert parse_verdict("not json at all").sufficient is True


def test_reflection_verdict_defaults():
    verdict = ReflectionVerdict(sufficient=True)
    assert verdict.missing == ""