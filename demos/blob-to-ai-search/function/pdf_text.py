from __future__ import annotations

import io

from pypdf import PdfReader


def extract_pages(data: bytes) -> list[str]:
    """Extract text per page from PDF bytes. Best-effort; never raises per page."""
    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - best-effort extraction for the demo
            pages.append("")
    return pages
