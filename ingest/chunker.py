from __future__ import annotations

import re

from ingest.models import Chunk, ParsedDoc, ParsedParagraph, ParsedTable

HEADING_ROLES = {"title", "sectionHeading"}


def derive_fund_name(section_path: str) -> str | None:
    """섹션 경로에서 '…기금/…계정' 형태의 기금명을 파생한다(가장 깊은 세그먼트 우선). 없으면 None."""
    for seg in reversed([s.strip() for s in section_path.split(">")]):
        m = re.search(r"([가-힣A-Za-z0-9·()]+(?:기금|계정))", seg)
        if m:
            return re.sub(r"^\d+\.\s*", "", m.group(1))
    return None


def derive_fund_scale(section_path: str, default: str | None = None) -> str | None:
    """섹션 경로 키워드로 기금 규모 유형을 파생한다. 없으면 default."""
    if "대규모" in section_path:
        return "대규모"
    if "대형" in section_path or "중소형" in section_path:
        return "대형중소형"
    return default


def _table_header(markdown: str) -> str:
    """표 마크다운의 헤더 행(첫 줄)을 반환. 없으면 빈 문자열."""
    return markdown.split("\n", 1)[0].strip() if markdown else ""


def _table_body(markdown: str) -> str:
    """헤더 행 + 구분선(|---|)을 제외한 본문 데이터 행만 반환."""
    lines = markdown.split("\n")
    return "\n".join(lines[2:]) if len(lines) > 2 else ""


def merge_continuation_tables(tables: list[ParsedTable]) -> list[ParsedTable]:
    """페이지 경계로 분리된 '연속 표'를 하나로 병합한다.

    DI(prebuilt-layout)는 페이지를 넘는 표를 이어붙이지 않고 페이지별 별개 표로
    출력한다. 다만 연속되는 조각은 (1) 다음 페이지에서 헤더 행을 반복하고,
    (2) caption이 없다(캡션은 표의 첫 조각에만 붙는다). 이 두 신호로 연속 조각을
    판별해 본문 행을 이어붙인다. caption을 가진 별개 표(예: '참고 7'/'참고 8')는
    헤더가 같아도 병합하지 않는다.

    판별 조건(모두 충족): 직전 표 바로 다음 물리 페이지 + 동일 헤더 행 + 조각 caption 없음.
    """
    ordered = sorted(tables, key=lambda t: t.offset)
    merged: list[ParsedTable] = []
    last_page: int | None = None
    for t in ordered:
        if (
            merged
            and not (t.caption or "").strip()
            and last_page is not None
            and t.page == last_page + 1
            and _table_header(t.markdown) == _table_header(merged[-1].markdown)
            and _table_body(t.markdown)
        ):
            prev = merged[-1]
            prev.markdown = prev.markdown + "\n" + _table_body(t.markdown)  # 본문 행 이어붙임
            last_page = t.page
            continue
        merged.append(t.model_copy())
        last_page = t.page
    return merged


def _printed_pages(doc: ParsedDoc) -> dict[int, int]:
    """physical page -> printed page number (from role=='pageNumber' paragraphs)."""
    out: dict[int, int] = {}
    for p in doc.paragraphs:
        if p.role == "pageNumber":
            m = re.search(r"\d+", p.content)
            if m:
                out[p.page] = int(m.group())
    return out


def _split_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap_chars
    return parts


def _heading_depth(text: str) -> int:
    """번호 스타일로 헤딩 깊이 추정: '1.'→1, '가.'→2, 'ㅇ'→3, 기타→1."""
    t = text.strip()
    if re.match(r"^\d+\.", t):
        return 1
    if re.match(r"^[가-힣]\.", t):
        return 2
    if t.startswith("ㅇ") or t.startswith("-"):
        return 3
    return 1


def chunk_document(
    doc: ParsedDoc, max_chars: int = 3600, overlap_chars: int = 540,
    *, year: int | None = None, doc_type: str | None = None, fund_scale_default: str | None = None,
) -> list[Chunk]:
    printed = _printed_pages(doc)
    chunks: list[Chunk] = []
    idx = 0
    heading_stack: list[str] = []
    buffer: list[ParsedParagraph] = []

    def flush() -> None:
        nonlocal idx
        if not buffer:
            return
        section_path = " > ".join(heading_stack)
        text = "\n".join(p.content for p in buffer).strip()
        start_page = buffer[0].page
        for piece in _split_text(text, max_chars, overlap_chars):
            chunks.append(
                Chunk(
                    id=f"{doc.doc_id}-{idx}",
                    doc_id=doc.doc_id,
                    content=piece,
                    chunk_type="narrative",
                    section_path=section_path,
                    page_physical=start_page,
                    page_printed=printed.get(start_page),
                    year=year,
                    doc_type=doc_type,
                    fund_name=derive_fund_name(section_path),
                    fund_scale=derive_fund_scale(section_path, fund_scale_default),
                )
            )
            idx += 1
        buffer.clear()

    # Merge paragraphs and tables into single stream ordered by offset
    items: list[tuple[str, ParsedParagraph | ParsedTable]] = []
    for p in doc.paragraphs:
        items.append(("paragraph", p))
    for t in merge_continuation_tables(doc.tables):
        items.append(("table", t))
    items.sort(key=lambda x: x[1].offset)

    for item_type, item in items:
        if item_type == "paragraph":
            p = item
            if p.role == "pageNumber":
                continue
            if p.role in HEADING_ROLES:
                flush()
                if p.role == "title":
                    heading_stack = [p.content]
                else:
                    depth = _heading_depth(p.content)
                    heading_stack = heading_stack[:depth] + [p.content]
                continue
            buffer.append(p)
        elif item_type == "table":
            # Flush narrative buffer FIRST, then emit table with current section_path
            flush()
            t = item
            content = (f"{t.caption}\n" if t.caption else "") + t.markdown
            section_path = " > ".join(heading_stack)
            chunks.append(
                Chunk(
                    id=f"{doc.doc_id}-{idx}",
                    doc_id=doc.doc_id,
                    content=content,
                    chunk_type="table",
                    section_path=section_path,
                    page_physical=t.page,
                    page_printed=printed.get(t.page),
                    year=year,
                    doc_type=doc_type,
                    fund_name=derive_fund_name(section_path),
                    fund_scale=derive_fund_scale(section_path, fund_scale_default),
                )
            )
            idx += 1

    flush()
    return chunks
