from __future__ import annotations

from pydantic import BaseModel


class CorpusDoc(BaseModel):
    pdf: str
    doc_id: str
    year: int
    doc_type: str  # "report" | "guideline"
    fund_scale: str | None = None
    expected_overall_grade_count: int | None = None
    expected_overall_grade_excluded_fund_ids: tuple[str, ...] = ()


CORPUS: list[CorpusDoc] = [
    CorpusDoc(pdf="Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf", doc_id="report-2025", year=2025, doc_type="report", expected_overall_grade_count=24, expected_overall_grade_excluded_fund_ids=("국민연금기금",)),
    CorpusDoc(pdf="Docs/2022회계연도기금운용평가보고서Ⅱ(자산운용부문).pdf", doc_id="report-2022", year=2022, doc_type="report", expected_overall_grade_count=30, expected_overall_grade_excluded_fund_ids=("국민연금기금",)),
    CorpusDoc(pdf="Docs/2021회계연도 기금운용평가보고서Ⅱ(자산운용부문).pdf", doc_id="report-2021", year=2021, doc_type="report", expected_overall_grade_count=32, expected_overall_grade_excluded_fund_ids=("국민연금기금",)),
    CorpusDoc(pdf="Docs/2021회계연도 기금운용평가지침1(대형중소형).pdf", doc_id="guideline-2021-dh", year=2021, doc_type="guideline", fund_scale="대형중소형"),
    CorpusDoc(pdf="Docs/2022회계연도 기금운용평가지침1(대형중소형부문).pdf", doc_id="guideline-2022-dh", year=2022, doc_type="guideline", fund_scale="대형중소형"),
]


def get_doc(doc_id: str) -> CorpusDoc | None:
    return next((d for d in CORPUS if d.doc_id == doc_id), None)
