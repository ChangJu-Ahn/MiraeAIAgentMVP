from __future__ import annotations

import re
from datetime import datetime, timezone

_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_\-=]")


def chunk_text(text: str, size: int = 1000) -> list[str]:
    """Split text into fixed-size chunks of `size` characters.

    Empty or whitespace-only input yields `[]`. The final chunk keeps the
    remainder and may be shorter than `size`.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    stripped = text.strip()
    if not stripped:
        return []
    return [stripped[i : i + size] for i in range(0, len(stripped), size)]


def sanitize_key(name: str) -> str:
    """Make a string safe for an Azure AI Search document key.

    Allowed key characters are letters, digits, `_`, `-`, `=`. Everything else
    becomes `_`. An empty result falls back to `doc`.
    """
    safe = _KEY_UNSAFE.sub("_", name)
    return safe or "doc"


def build_documents(
    source_file: str,
    pages: list[str],
    chunk_size: int = 1000,
    uploaded_at: datetime | None = None,
) -> list[dict]:
    """Build AI Search documents from per-page text.

    Each page is chunked independently so `page` is exact. `chunk_index` is a
    document-global counter. Ids are deterministic so re-uploads overwrite.
    """
    ts = (uploaded_at or datetime.now(timezone.utc)).isoformat()
    key_base = sanitize_key(source_file)
    docs: list[dict] = []
    chunk_index = 0
    for page_number, page_text in enumerate(pages, start=1):
        for chunk in chunk_text(page_text, chunk_size):
            docs.append(
                {
                    "id": f"{key_base}-{chunk_index}",
                    "content": chunk,
                    "source_file": source_file,
                    "chunk_index": chunk_index,
                    "page": page_number,
                    "uploaded_at": ts,
                }
            )
            chunk_index += 1
    return docs
