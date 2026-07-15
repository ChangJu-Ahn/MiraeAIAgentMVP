from __future__ import annotations

from pydantic import BaseModel


class GoldenItem(BaseModel):
    id: str
    question: str
    qtype: str
    ground_truth: str | None = None
    sheet: str | None = None
    row_number: int | None = None


GOLDEN_QA: list[GoldenItem] = [
    # 단일검색
    GoldenItem(id="q01", question="자산운용부문 평가의 목적은 무엇인가요?", qtype="단일검색"),
    GoldenItem(id="q02", question="기금운용평가단은 어떻게 구성되나요?", qtype="단일검색"),
    GoldenItem(id="q03", question="자산운용 평가의 근거가 되는 법령은 무엇인가요?", qtype="단일검색"),
    # 표데이터
    GoldenItem(id="q04", question="기금운용평가 종합등급에는 어떤 등급들이 있나요?", qtype="표데이터"),
    GoldenItem(id="q05", question="탁월 등급과 우수 등급의 정의 차이는 무엇인가요?", qtype="표데이터"),
    GoldenItem(id="q06", question="대규모 기금의 계량평가 지표에는 어떤 것이 있나요?", qtype="표데이터"),
    # 다년도
    GoldenItem(id="q07", question="전기 평가결과 대비 평가 방식의 변화가 있었나요?", qtype="다년도"),
    GoldenItem(id="q08", question="평가 등급 구간은 몇 단계로 구분되나요?", qtype="다년도"),
    # 다중문서교차
    GoldenItem(id="q09", question="대형·중소형 기금과 대규모 기금의 평가 방법은 어떻게 다른가요?", qtype="다중문서교차"),
    GoldenItem(id="q10", question="혁신성장 분야 투자에 대한 가점은 어떻게 부여되나요?", qtype="다중문서교차"),
    # 종합요약
    GoldenItem(id="q11", question="2025회계연도 자산운용부문 평가의 특징을 요약해 주세요.", qtype="종합요약"),
    GoldenItem(id="q12", question="평가결과 공개 방식을 요약해 주세요.", qtype="종합요약"),
    # 원문부재 (할루시네이션 방어)
    GoldenItem(id="q13", question="이 보고서에 나온 2025년 애플 아이폰 판매량은 얼마인가요?", qtype="원문부재"),
    GoldenItem(id="q14", question="이 보고서에서 삼성전자 반도체 매출 전망치는 얼마로 나오나요?", qtype="원문부재"),
    GoldenItem(id="q15", question="보고서에 기재된 비트코인 목표가는 얼마인가요?", qtype="원문부재"),
    # 추가 단일/표/교차
    GoldenItem(id="q16", question="단기자금 통합운용 제도 참여 기금에 대한 가점 기준은?", qtype="단일검색"),
    GoldenItem(id="q17", question="대형 기금과 중소형 기금은 어떤 기준으로 구분되나요?", qtype="표데이터"),
    GoldenItem(id="q18", question="비계량평가와 계량평가는 각각 무엇을 평가하나요?", qtype="다중문서교차"),
]
