from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

from pydantic import BaseModel

from config.settings import get_settings
from ingest.corpus import CORPUS


class IndexedDocument(BaseModel):
    doc_id: str
    source_file: str
    source_url: str | None = None
    year: int | None = None
    doc_type: str


def indexed_documents() -> list[IndexedDocument]:
    endpoint = get_settings().ingest_api_endpoint.rstrip("/")
    if endpoint:
        with urlopen(f"{endpoint}/api/documents", timeout=30) as response:
            records = json.load(response)
        return [IndexedDocument.model_validate(record) for record in records]
    return [
        IndexedDocument(
            doc_id=d.doc_id, source_file=Path(d.pdf).name, year=d.year, doc_type=d.doc_type,
        ) for d in CORPUS
    ]
