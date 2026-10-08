from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class ParsedParagraph(BaseModel):
    role: str | None
    content: str
    page: int
    offset: int = 0
    region_type: str | None = None


class ParsedTable(BaseModel):
    markdown: str
    page: int
    caption: str | None = None
    offset: int = 0
    bounding_regions: str | None = None


class ParsedFigure(BaseModel):
    page: int
    polygon: list[float]
    offset: int = 0
    caption: str | None = None
    figure_id: str | None = None
    image_path: Path | None = None
    image_blob: str | None = None
    bounding_regions: str | None = None


class ParsedDoc(BaseModel):
    doc_id: str
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
    doc_type: str | None = None
    fund_name: str | None = None
    fund_scale: str | None = None
    fund_id: str | None = None
    ministry: str | None = None
    content_vector: list[float] | None = None
    source_file: str | None = None
    source_url: str | None = None
    image_url: str | None = None
    bounding_regions: str | None = None
