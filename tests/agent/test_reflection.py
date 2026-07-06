from agent.reflection import ReflectionVerdict, augmented_question, parse_verdict


def test_augmented_question_includes_missing():
    q = augmented_question("탁월 등급이란?", "우수 등급과의 점수 구간 차이")
    assert "탁월 등급이란?" in q
    assert "우수 등급과의 점수 구간 차이" in q


def test_parse_verdict_json():
    v = parse_verdict('{"sufficient": false, "missing": "연도별 수치"}')
    assert v.sufficient is False and "연도별" in v.missing


def test_parse_verdict_embedded_and_fallback():
    v = parse_verdict('점검 결과: {"sufficient": true, "missing": ""} 입니다')
    assert v.sufficient is True
    bad = parse_verdict("not json at all")
    assert bad.sufficient is True


def test_reflection_verdict_defaults():
    v = ReflectionVerdict(sufficient=True)
    assert v.missing == ""
