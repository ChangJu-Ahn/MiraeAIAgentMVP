from __future__ import annotations

import json
import os
from pathlib import Path

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    AnalyzeResult,
    DocumentAnalysisFeature,
    DocumentContentFormat,
)
from azure.identity import DefaultAzureCredential

from config.settings import get_settings
from ingest.models import ParsedDoc, ParsedParagraph, ParsedTable

CACHE_DIR = Path(".ingest_cache")


def _table_to_markdown(table: dict) -> str:
    rows = table["rowCount"]
    cols = table["columnCount"]
    if rows == 0 or cols == 0:
        return ""
    grid = [["" for _ in range(cols)] for _ in range(rows)]
    for cell in table["cells"]:
        r, c = cell["rowIndex"], cell["columnIndex"]
        if r < rows and c < cols:
            content = (cell.get("content") or "").replace("\n", " ").replace("|", "\\|").strip()
            grid[r][c] = content
    lines = ["| " + " | ".join(grid[0]) + " |", "|" + "|".join(["---"] * cols) + "|"]
    for row in grid[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _page_of(element: dict) -> int:
    regions = element.get("boundingRegions") or []
    return regions[0]["pageNumber"] if regions else 1


def _result_to_parsed(doc_id: str, data: dict) -> ParsedDoc:
    paragraphs = [
        ParsedParagraph(role=p.get("role"), content=p.get("content", ""), page=_page_of(p))
        for p in data.get("paragraphs", [])
    ]
    tables = [
        ParsedTable(markdown=_table_to_markdown(t), page=_page_of(t))
        for t in data.get("tables", [])
    ]
    return ParsedDoc(
        doc_id=doc_id,
        markdown=data.get("content", ""),
        paragraphs=paragraphs,
        tables=tables,
    )


def analyze_pdf(
    pdf_path: str, doc_id: str, pages: str | None = None, use_cache: bool = True
) -> ParsedDoc:
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{doc_id}.json"
    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return _result_to_parsed(doc_id, data)

    s = get_settings()
    client = DocumentIntelligenceClient(
        endpoint=s.doc_intelligence_endpoint, credential=DefaultAzureCredential()
    )
    with open(pdf_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            AnalyzeDocumentRequest(bytes_source=f.read()),
            pages=pages,
            output_content_format=DocumentContentFormat.MARKDOWN,
            features=[DocumentAnalysisFeature.KEY_VALUE_PAIRS],
        )
    result: AnalyzeResult = poller.result()
    data = result.as_dict()
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return _result_to_parsed(doc_id, data)
