from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    search_endpoint: str
    index_name: str
    storage_blob_endpoint: str
    upload_container: str
    chunk_size: int
    max_upload_mb: int


def load_config(env: dict[str, str] | None = None) -> Config:
    e = env if env is not None else os.environ
    return Config(
        search_endpoint=e.get("SEARCH_ENDPOINT", ""),
        index_name=e.get("SEARCH_INDEX_NAME", "demo-blob-index"),
        storage_blob_endpoint=e.get("STORAGE_BLOB_ENDPOINT", ""),
        upload_container=e.get("UPLOAD_CONTAINER", "pdfs"),
        chunk_size=int(e.get("CHUNK_SIZE", "1000")),
        max_upload_mb=int(e.get("MAX_UPLOAD_MB", "50")),
    )
