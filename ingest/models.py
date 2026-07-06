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


class ParsedFigure(BaseModel):
    page: int
    polygon: list[float]
    offset: int = 0
    caption: str | None = None


class ParsedDoc(BaseModel):
    doc_id: str
    markdown: str
    paragraphs: list[ParsedParagraph]
    tables: list[ParsedTable]
    figures: list[ParsedFigure] = []


class Chunk(BaseModel):
    id: str
    doc_id: str
    content: str
    chunk_type: str  # "narrative" | "table" | "figure"
    section_path: str
    page_printed: int | None = None
    page_physical: int
    year: int | None = None
    fund_name: str | None = None
    content_vector: list[float] | None = None
