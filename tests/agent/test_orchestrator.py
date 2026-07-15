import inspect

from agent import orchestrator
from agent.orchestrator import ask_sync, SYSTEM_PROMPT


def test_system_prompt_has_today_placeholder_and_filter_rule():
    assert "{today}" in SYSTEM_PROMPT
    assert "필터" in SYSTEM_PROMPT and "최신" in SYSTEM_PROMPT


def test_system_prompt_requires_output_only_in_the_users_input_language():
    assert "현재 사용자 메시지의 주된 자연어" in SYSTEM_PROMPT
    assert "오직 그 언어로만" in SYSTEM_PROMPT
    assert "다른 자연어의 단어·문장" in SYSTEM_PROMPT
    assert "도구 결과의 언어에 영향받지" in SYSTEM_PROMPT


def test_request_context_expands_year_range_and_identifies_document_type():
    years, doc_type = orchestrator._request_context(
        "공무원연금기금의 2023~2025회계연도 최종등급 추이는?"
    )
    assert years == [2023, 2024, 2025]
    assert doc_type == "report"

    years, doc_type = orchestrator._request_context(
        "2026회계연도 기금운용평가지침의 계량 지표는?"
    )
    assert years == [2026]
    assert doc_type == "guideline"


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


def test_reasoning_options_and_stream_api_accept_user_effort():
    assert orchestrator._reasoning_options("low") == {
        "reasoning": {"effort": "low", "summary": "auto"}
    }
    assert orchestrator._reasoning_options("invalid") == {
        "reasoning": {"effort": "medium", "summary": "auto"}
    }
    assert list(inspect.signature(orchestrator.start_stream).parameters) == [
        "question",
        "effort",
        "session",
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Task 6 — Prompt routing rules
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptRoutingRules:
    """System prompt must route structured intents to catalog/aggregation tools."""

    def test_global_intent_keywords_in_prompt(self):
        for kw in ["전체", "각 기금", "상위", "하위", "순위", "가장"]:
            assert kw in SYSTEM_PROMPT, f"Missing routing keyword: {kw}"

    def test_structured_tools_mentioned(self):
        assert "list_funds" in SYSTEM_PROMPT
        assert "aggregate_evaluations" in SYSTEM_PROMPT
        assert "fund_analytics" in SYSTEM_PROMPT

    def test_llm_arithmetic_is_forbidden(self):
        assert "LLM" in SYSTEM_PROMPT
        assert "계산" in SYSTEM_PROMPT or "집합" in SYSTEM_PROMPT

    def test_forbids_repeated_topk_for_ranking(self):
        # Must say not to use repeated semantic top-k for numeric sorting
        assert "top-k" in SYSTEM_PROMPT or "반복" in SYSTEM_PROMPT

    def test_incomplete_coverage_disclosure(self):
        # Must instruct disclosure of incomplete coverage
        assert "불완전" in SYSTEM_PROMPT or "누락" in SYSTEM_PROMPT or "공개" in SYSTEM_PROMPT or "부족" in SYSTEM_PROMPT or "미포함" in SYSTEM_PROMPT

    def test_quantitative_rank_with_final_grade_uses_evaluated_population(self):
        assert "population='evaluated'" in SYSTEM_PROMPT
        assert "overall_grade" in SYSTEM_PROMPT
        assert "asset_management_performance" in SYSTEM_PROMPT
        assert "교집합" in SYSTEM_PROMPT
        assert "order='desc'" in SYSTEM_PROMPT
        assert "점수와 순위" in SYSTEM_PROMPT

    def test_unknown_fund_uses_catalog_absence_evidence(self):
        assert "resolve_fund가 0건" in SYSTEM_PROMPT
        assert "list_funds" in SYSTEM_PROMPT
        assert "평가 대상 기금이 아니다" in SYSTEM_PROMPT
        assert "시맨틱 검색으로 부재를 재확인하지 마라" in SYSTEM_PROMPT

    def test_adjustment_questions_use_structured_facts(self):
        assert "가감점" in SYSTEM_PROMPT
        assert "metric='가감점'" in SYSTEM_PROMPT
        assert "get_fund_evaluations" in SYSTEM_PROMPT

    def test_annual_summary_uses_distribution_and_rank(self):
        assert "연도 전체 평가결과" in SYSTEM_PROMPT
        assert "operation='distribution'" in SYSTEM_PROMPT
        assert "operation='rank'" in SYSTEM_PROMPT
        assert "최상·최하 종합등급" in SYSTEM_PROMPT

    def test_combined_grade_performance_answer_omits_metric_grade(self):
        assert "계량 성과 자체의 세부등급은 덧붙이지 마라" in SYSTEM_PROMPT

    def test_cross_year_remediation_matches_same_issues(self):
        assert "지적사항이 다음 연도에 개선됐는지" in SYSTEM_PROMPT
        assert "미흡점·개선방안·권고" in SYSTEM_PROMPT
        assert "동일한 주제어" in SYSTEM_PROMPT
        assert "개선·미개선·부분개선" in SYSTEM_PROMPT
        assert "다른 수치 항목으로 대체하지 마라" in SYSTEM_PROMPT
        assert "위원 겸직과 참석률은 별개 항목" in SYSTEM_PROMPT
        assert "'위원 겸직'과 '참석률'의 별도 검색" in SYSTEM_PROMPT
        assert "모두 완료하기 전에는 답하지 마라" in SYSTEM_PROMPT
        assert "검색한 모든 지적사항" in SYSTEM_PROMPT
        assert "참석률 판정" in SYSTEM_PROMPT

    def test_missing_document_forbids_filter_widening_or_substitution(self):
        assert "corpus manifest" in SYSTEM_PROMPT
        assert "연도·문서유형 필터를 제거하지 마라" in SYSTEM_PROMPT
        assert "다른 연도나 문서유형으로 대체하지 마라" in SYSTEM_PROMPT

    def test_fact_source_citation(self):
        # Must instruct citation of fact sources
        assert "출처" in SYSTEM_PROMPT
