from __future__ import annotations

from pydantic import BaseModel


class ParsedParagraph(BaseModel):
    role: str | None
    content: str
    page: int
    offset: int = 0


class ParsedTable(BaseModel):
    markdown: str
    page: int
    caption: str | None = None
    offset: int = 0


class ParsedDoc(BaseModel):
    doc_id: str
    markdown: str
    paragraphs: list[ParsedParagraph]
    tables: list[ParsedTable]


class Chunk(BaseModel):
    id: str
    doc_id: str
    content: str
    chunk_type: str  # "narrative" | "table"
    section_path: str
    page_printed: int | None = None
    page_physical: int
    year: int | None = None
    fund_name: str | None = None
    content_vector: list[float] | None = None
