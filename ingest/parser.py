from __future__ import annotations

import json
import hashlib
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
from ingest.models import ParsedDoc, ParsedFigure, ParsedParagraph, ParsedTable

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


def _offset_of(element: dict) -> int:
    """Extract document offset from DI element spans."""
    spans = element.get("spans") or []
    return spans[0]["offset"] if spans else 0


def _result_to_parsed(doc_id: str, data: dict) -> ParsedDoc:
    def region_type(paragraph: dict, index: int) -> str | None:
        for kind in ("table", "figure"):
            for region in data.get(f"{kind}s", []):
                if f"/paragraphs/{index}" in region.get("elements", []):
                    return kind
                spans = region.get("spans", [])
                for span in paragraph.get("spans", []):
                    start, end = span["offset"], span["offset"] + span["length"]
                    if any(s["offset"] <= start and end <= s["offset"] + s["length"]
                           for s in spans):
                        return kind
        return None

    paragraphs = [
        ParsedParagraph(
            role=p.get("role"), content=p.get("content", ""), page=_page_of(p),
            offset=_offset_of(p), region_type=region_type(p, i),
        )
        for i, p in enumerate(data.get("paragraphs", []))
    ]
    tables = [
        ParsedTable(
            markdown=_table_to_markdown(t),
            page=_page_of(t),
            offset=_offset_of(t),
            caption=(t.get("caption") or {}).get("content"),
            bounding_regions=json.dumps(t.get("boundingRegions", [])),
        )
        for t in data.get("tables", [])
    ]
    figures = [
        ParsedFigure(
            page=_page_of(f),
            polygon=((f.get("boundingRegions") or [{}])[0].get("polygon") or []),
            offset=_offset_of(f),
            caption=(f.get("caption") or {}).get("content"),
            figure_id=f.get("id"),
            image_path=f.get("_image_path"),
            bounding_regions=json.dumps(f.get("boundingRegions", [])),
        )
        for f in data.get("figures", [])
        if (f.get("boundingRegions") or [{}])[0].get("polygon")
    ]
    return ParsedDoc(
        doc_id=doc_id,
        paragraphs=paragraphs,
        tables=tables,
        figures=figures,
    )


def analyze_pdf(
    pdf_path: str, doc_id: str, pages: str | None = None, use_cache: bool = True,
    *, cache_dir: Path | None = None,
) -> ParsedDoc:
    content = Path(pdf_path).read_bytes()
    key = hashlib.sha256(content + f"\0{pages}\0layout-figures-v1".encode()).hexdigest()
    directory = (cache_dir or CACHE_DIR) / key
    directory.mkdir(parents=True, exist_ok=True)
    cache_file = directory / "layout.json"
    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if all(Path(f["_image_path"]).is_file() for f in data.get("figures", [])
               if f.get("id")):
            return _result_to_parsed(doc_id, data)

    s = get_settings()
    client = DocumentIntelligenceClient(
        endpoint=s.doc_intelligence_endpoint, credential=DefaultAzureCredential()
    )
    poller = client.begin_analyze_document(
        "prebuilt-layout",
        AnalyzeDocumentRequest(bytes_source=content),
        pages=pages,
        output_content_format=DocumentContentFormat.MARKDOWN,
        features=[DocumentAnalysisFeature.KEY_VALUE_PAIRS],
        output=["figures"],
    )
    result: AnalyzeResult = poller.result()
    data = result.as_dict()
    for i, figure in enumerate(data.get("figures", [])):
        if not figure.get("id"):
            raise ValueError("Document Intelligence returned a figure without an id")
        image = b"".join(client.get_analyze_result_figure(
            model_id=data["modelId"], result_id=poller.details["operation_id"],
            figure_id=figure["id"],
        ))
        if not image:
            raise ValueError(f"Empty image for figure {figure['id']}")
        image_path = directory / f"figure-{i}.png"
        image_path.write_bytes(image)
        figure["_image_path"] = str(image_path.resolve())
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return _result_to_parsed(doc_id, data)
