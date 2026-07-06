from __future__ import annotations

import re

from ingest.models import Chunk, ParsedDoc, ParsedParagraph

HEADING_ROLES = {"title", "sectionHeading"}


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


def chunk_document(doc: ParsedDoc, max_chars: int = 3600, overlap_chars: int = 540) -> list[Chunk]:
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
                )
            )
            idx += 1
        buffer.clear()

    for p in doc.paragraphs:
        if p.role == "pageNumber":
            continue
        if p.role in HEADING_ROLES:
            flush()
            # 헤딩 레벨: title=0, sectionHeading은 번호 패턴으로 깊이 추정
            if p.role == "title":
                heading_stack = [p.content]
            else:
                depth = _heading_depth(p.content)
                heading_stack = heading_stack[:depth] + [p.content]
            continue
        buffer.append(p)
    flush()

    for t in doc.tables:
        content = (f"{t.caption}\n" if t.caption else "") + t.markdown
        chunks.append(
            Chunk(
                id=f"{doc.doc_id}-{idx}",
                doc_id=doc.doc_id,
                content=content,
                chunk_type="table",
                section_path=" > ".join(heading_stack),
                page_physical=t.page,
                page_printed=printed.get(t.page),
            )
        )
        idx += 1
    return chunks
