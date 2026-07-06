from ingest.models import ParsedDoc, ParsedParagraph, ParsedTable


def make_doc() -> ParsedDoc:
    paras = [
        ParsedParagraph(role="title", content="Ⅱ. 자산운용부문 평가결과", page=1),
        ParsedParagraph(role="sectionHeading", content="1. 평가 개요", page=1),
        ParsedParagraph(role="sectionHeading", content="가. 평가의 특징", page=1),
        ParsedParagraph(role=None, content="가나다 " * 500, page=1),  # 긴 문단 → 분할
        ParsedParagraph(role="pageNumber", content="- 24 -", page=1),
        ParsedParagraph(role="sectionHeading", content="나. 평가결과 공개", page=2),
        ParsedParagraph(role=None, content="짧은 문단.", page=2),
    ]
    tables = [ParsedTable(markdown="| 등급 | 내용 |\n|---|---|\n| 탁월 | 높음 |", page=2, caption="종합등급")]
    return ParsedDoc(doc_id="d1", markdown="", paragraphs=paras, tables=tables)
