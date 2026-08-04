# Blob → Azure Function → AI Search Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uploading a PDF from a Function-served web page lands the extracted, statically-chunked text into a new Azure AI Search index — no embeddings.

**Architecture:** One Python Azure Function App hosts two functions: an HTTP-triggered `upload` page that writes the PDF to a new `pdfs` blob container, and an Event Grid-triggered `index` that downloads the blob, extracts text with pypdf, splits it into fixed 1000-char chunks, and uploads documents to `demo-blob-index`. Reuses the existing Storage account and AI Search service; the Chainlit app and `main.bicep` are untouched.

**Tech Stack:** Python 3.12, Azure Functions v2 (Consumption Y1 Linux), azure-functions, azure-identity, azure-search-documents, azure-storage-blob, pypdf, Bicep, Azure CLI, Event Grid.

## Global Constraints

- Python: `>=3.12,<3.13`.
- Subscription: `347e0df7-94e9-4feb-b42d-57d7e49566f2`; Resource Group: `rg-mirae-ai-agent-poc`; Location: `koreacentral`.
- Reuse the **existing** Storage account (add only container `pdfs`) and the **existing** AI Search service (add only index `demo-blob-index`).
- Do **not** modify `infra/main.bicep`, the Container App, the Chainlit app, or existing indexes.
- All Azure data-plane access uses **managed identity + RBAC** — the Search service has `disableLocalAuth: true` (no keys).
- No embeddings / vectors. Static chunking only: fixed **1000** characters.
- Upload HTTP endpoint uses **anonymous** auth (demo only).
- Function pure-logic modules must import only stdlib (no `azure.*`, no `pypdf`) so the repo test suite can import them without new dependencies.
- Run tests with `uv run pytest`.

---

### Task 1: Pure chunking and document building

**Files:**
- Create: `functions/blob_to_search/chunking.py`
- Create: `tests/conftest.py`
- Test: `tests/test_blob_chunking.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `chunk_text(text: str, size: int = 1000) -> list[str]`
  - `sanitize_key(name: str) -> str`
  - `build_documents(source_file: str, pages: list[str], chunk_size: int = 1000, uploaded_at: datetime | None = None) -> list[dict]` — each dict has keys `id, content, source_file, chunk_index, page, uploaded_at`.

- [ ] **Step 1: Create the test path shim so tests can import the function's flat modules**

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

# The Azure Functions app (functions/blob_to_search) uses flat module imports
# (e.g. `import chunking`, `import func_config`). Append its directory so the
# repo test suite can import those pure modules. It is appended (not inserted at
# position 0) so the repo's own top-level packages — notably `config` — keep
# precedence and are never shadowed by a flat module of the same name.
_FUNC_DIR = str(Path(__file__).resolve().parent.parent / "functions" / "blob_to_search")
if _FUNC_DIR not in sys.path:
    sys.path.append(_FUNC_DIR)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_blob_chunking.py`:

```python
import re
from datetime import datetime, timezone

import chunking


def test_chunk_text_splits_by_size():
    assert chunking.chunk_text("abcdef", 2) == ["ab", "cd", "ef"]


def test_chunk_text_keeps_remainder():
    assert chunking.chunk_text("abcde", 2) == ["ab", "cd", "e"]


def test_chunk_text_shorter_than_size():
    assert chunking.chunk_text("abc", 10) == ["abc"]


def test_chunk_text_empty_or_whitespace():
    assert chunking.chunk_text("", 10) == []
    assert chunking.chunk_text("   \n\t ", 10) == []


def test_chunk_text_unicode_by_char():
    assert chunking.chunk_text("가나다라", 2) == ["가나", "다라"]


def test_chunk_text_rejects_nonpositive_size():
    import pytest

    with pytest.raises(ValueError):
        chunking.chunk_text("abc", 0)


def test_sanitize_key_only_safe_chars():
    out = chunking.sanitize_key("2025 보고서.pdf")
    assert re.fullmatch(r"[A-Za-z0-9_\-=]+", out)


def test_sanitize_key_empty_fallback():
    assert chunking.sanitize_key("") == "doc"


def test_build_documents_pages_and_indexes():
    pages = ["A" * 5, "B" * 3]
    docs = chunking.build_documents(
        "f.pdf", pages, chunk_size=2,
        uploaded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert len(docs) == 5
    assert [d["page"] for d in docs] == [1, 1, 1, 2, 2]
    assert [d["chunk_index"] for d in docs] == [0, 1, 2, 3, 4]
    assert docs[0]["id"] == "f_pdf-0"
    assert docs[0]["content"] == "AA"
    assert docs[0]["source_file"] == "f.pdf"
    assert docs[0]["uploaded_at"] == "2026-01-01T00:00:00+00:00"


def test_build_documents_skips_empty_pages():
    assert chunking.build_documents("f.pdf", ["", "   "], chunk_size=100) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_blob_chunking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chunking'`.

- [ ] **Step 4: Write minimal implementation**

Create `functions/blob_to_search/chunking.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_blob_chunking.py -v`
Expected: PASS (all 10 tests).

- [ ] **Step 6: Commit**

```bash
git add functions/blob_to_search/chunking.py tests/conftest.py tests/test_blob_chunking.py
git commit -m "feat(blob-demo): add pure text chunking and document builder"
```

---

### Task 2: Upload page HTML and validation

**Files:**
- Create: `functions/blob_to_search/upload_page.py`
- Test: `tests/test_blob_upload_page.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `validate_upload(filename: str, size_bytes: int, max_mb: int) -> str | None` — returns an error message or `None` when valid.
  - `render_form_html() -> str`
  - `render_result_html(filename: str) -> str`
  - `render_error_html(message: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_blob_upload_page.py`:

```python
import upload_page


def test_validate_rejects_non_pdf():
    assert upload_page.validate_upload("a.txt", 10, 50) is not None


def test_validate_rejects_too_large():
    assert upload_page.validate_upload("a.pdf", 60 * 1024 * 1024, 50) is not None


def test_validate_rejects_empty_file_and_name():
    assert upload_page.validate_upload("a.pdf", 0, 50) is not None
    assert upload_page.validate_upload("", 10, 50) is not None


def test_validate_accepts_pdf_case_insensitive():
    assert upload_page.validate_upload("Report.PDF", 1234, 50) is None


def test_render_form_has_upload_controls():
    html = upload_page.render_form_html()
    assert "<form" in html
    assert 'type="file"' in html
    assert "/api/upload" in html
    assert 'method="post"' in html.lower()


def test_render_result_escapes_filename():
    html = upload_page.render_result_html("<script>.pdf")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_error_escapes_message():
    html = upload_page.render_error_html("bad <x>")
    assert "<x>" not in html
    assert "&lt;x&gt;" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_blob_upload_page.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'upload_page'`.

- [ ] **Step 3: Write minimal implementation**

Create `functions/blob_to_search/upload_page.py`:

```python
from __future__ import annotations

from html import escape

_PDF_SUFFIX = ".pdf"

_PAGE_CSS = """
  * { box-sizing: border-box; }
  body { margin: 0; background: #f5f7f8; color: #182026;
         font-family: "Noto Sans KR", sans-serif; }
  main { width: min(560px, calc(100% - 32px)); margin: 0 auto; padding: 56px 0; }
  h1 { font-size: 1.6rem; }
  .card { background: #fff; border: 1px solid #d7dde1; border-radius: 10px;
          padding: 24px; }
  input[type=file] { display: block; margin: 16px 0; }
  button { background: #006b5f; color: #fff; border: 0; border-radius: 6px;
           padding: 10px 18px; font-weight: 700; cursor: pointer; }
  .msg { margin-top: 18px; }
  .ok { color: #006b5f; } .err { color: #b4231f; }
  a { color: #006b5f; }
"""


def _shell(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title><style>{_PAGE_CSS}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def validate_upload(filename: str, size_bytes: int, max_mb: int) -> str | None:
    """Return an error message if the upload is invalid, else None."""
    if not filename:
        return "파일 이름이 없습니다."
    if not filename.lower().endswith(_PDF_SUFFIX):
        return "PDF 파일만 업로드할 수 있습니다."
    if size_bytes <= 0:
        return "빈 파일입니다."
    if size_bytes > max_mb * 1024 * 1024:
        return f"파일이 너무 큽니다. 최대 {max_mb}MB까지 허용됩니다."
    return None


def render_form_html() -> str:
    body = (
        "<h1>PDF 업로드 데모</h1>"
        "<div class=\"card\">"
        "<p>PDF를 올리면 blob에 저장되고, 이벤트로 Function이 실행되어 "
        "AI Search 인덱스에 적재됩니다.</p>"
        "<form action=\"/api/upload\" method=\"post\" enctype=\"multipart/form-data\">"
        "<input type=\"file\" name=\"file\" accept=\"application/pdf\" required>"
        "<button type=\"submit\">업로드</button>"
        "</form></div>"
    )
    return _shell("PDF 업로드 데모", body)


def render_result_html(filename: str) -> str:
    safe = escape(filename)
    body = (
        "<h1>업로드 완료</h1>"
        "<div class=\"card\">"
        f"<p class=\"msg ok\"><strong>{safe}</strong> 업로드 완료. "
        "잠시 후 Function이 실행되어 인덱싱됩니다.</p>"
        "<p><a href=\"/api/upload\">다른 파일 올리기</a></p>"
        "</div>"
    )
    return _shell("업로드 완료", body)


def render_error_html(message: str) -> str:
    body = (
        "<h1>업로드 실패</h1>"
        "<div class=\"card\">"
        f"<p class=\"msg err\">{escape(message)}</p>"
        "<p><a href=\"/api/upload\">다시 시도</a></p>"
        "</div>"
    )
    return _shell("업로드 실패", body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_blob_upload_page.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add functions/blob_to_search/upload_page.py tests/test_blob_upload_page.py
git commit -m "feat(blob-demo): add upload page HTML and validation"
```

---

### Task 3: Runtime configuration

**Files:**
- Create: `functions/blob_to_search/func_config.py`
- Test: `tests/test_blob_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Config` frozen dataclass with fields `search_endpoint, index_name, storage_blob_endpoint, upload_container, chunk_size, max_upload_mb`.
  - `load_config(env: dict[str, str] | None = None) -> Config`.

> **Naming:** the module is `func_config.py` (not `config.py`) on purpose. The
> repo already has a top-level `config/` package (`config.settings`), and a flat
> `config` module on `sys.path` would shadow it and break the rest of the suite.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_blob_config.py`:

```python
import func_config


def test_load_config_defaults():
    c = func_config.load_config({})
    assert c.index_name == "demo-blob-index"
    assert c.upload_container == "pdfs"
    assert c.chunk_size == 1000
    assert c.max_upload_mb == 50
    assert c.search_endpoint == ""


def test_load_config_overrides():
    c = func_config.load_config(
        {"CHUNK_SIZE": "500", "SEARCH_ENDPOINT": "https://s", "MAX_UPLOAD_MB": "10"}
    )
    assert c.chunk_size == 500
    assert c.search_endpoint == "https://s"
    assert c.max_upload_mb == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_blob_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'func_config'`.

> Note: this imports the function-local `func_config.py` via the `tests/conftest.py` path shim from Task 1. Because the shim *appends* the function dir, the repo's own `config/` package keeps precedence and is not shadowed.

- [ ] **Step 3: Write minimal implementation**

Create `functions/blob_to_search/func_config.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_blob_config.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add functions/blob_to_search/func_config.py tests/test_blob_config.py
git commit -m "feat(blob-demo): add runtime config loader"
```

---

### Task 4: Azure data-plane wrappers (blob, PDF, search)

**Files:**
- Create: `functions/blob_to_search/pdf_text.py`
- Create: `functions/blob_to_search/blob_io.py`
- Create: `functions/blob_to_search/search_index.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `pdf_text.extract_pages(data: bytes) -> list[str]`
  - `blob_io.download_blob(account_url: str, container: str, blob_name: str) -> bytes`
  - `blob_io.upload_blob(account_url: str, container: str, blob_name: str, data: bytes) -> None`
  - `search_index.ensure_index(endpoint: str, name: str) -> None`
  - `search_index.upload_documents(endpoint: str, name: str, documents: list[dict]) -> int`

> These wrap `azure.*` / `pypdf`, which are not installed in the repo env, so they are validated by `py_compile` here and exercised end-to-end in Task 10 — not by unit tests (keeps the repo test suite dependency-free per Global Constraints).

- [ ] **Step 1: Write `pdf_text.py`**

Create `functions/blob_to_search/pdf_text.py`:

```python
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
```

- [ ] **Step 2: Write `blob_io.py`**

Create `functions/blob_to_search/blob_io.py`:

```python
from __future__ import annotations

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient

_CRED = DefaultAzureCredential()


def download_blob(account_url: str, container: str, blob_name: str) -> bytes:
    client = BlobClient(account_url, container, blob_name, credential=_CRED)
    return client.download_blob().readall()


def upload_blob(account_url: str, container: str, blob_name: str, data: bytes) -> None:
    client = BlobClient(account_url, container, blob_name, credential=_CRED)
    client.upload_blob(data, overwrite=True)
```

- [ ] **Step 3: Write `search_index.py`**

Create `functions/blob_to_search/search_index.py`:

```python
from __future__ import annotations

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchableField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
)

_CRED = DefaultAzureCredential()


def build_index(name: str) -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(
            name="content", type=SearchFieldDataType.String, analyzer_name="ko.lucene"
        ),
        SimpleField(
            name="source_file", type=SearchFieldDataType.String,
            filterable=True, facetable=True,
        ),
        SimpleField(
            name="chunk_index", type=SearchFieldDataType.Int32,
            filterable=True, sortable=True,
        ),
        SimpleField(name="page", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(
            name="uploaded_at", type=SearchFieldDataType.DateTimeOffset,
            filterable=True, sortable=True,
        ),
    ]
    return SearchIndex(name=name, fields=fields)


def ensure_index(endpoint: str, name: str) -> None:
    client = SearchIndexClient(endpoint=endpoint, credential=_CRED)
    client.create_or_update_index(build_index(name))


def upload_documents(endpoint: str, name: str, documents: list[dict]) -> int:
    if not documents:
        return 0
    client = SearchClient(endpoint=endpoint, index_name=name, credential=_CRED)
    for i in range(0, len(documents), 1000):
        client.merge_or_upload_documents(documents=documents[i : i + 1000])
    return len(documents)
```

- [ ] **Step 4: Syntax-check all three modules**

Run: `python -m py_compile functions/blob_to_search/pdf_text.py functions/blob_to_search/blob_io.py functions/blob_to_search/search_index.py && echo OK`
Expected: `OK` (no output from py_compile, then `OK`).

- [ ] **Step 5: Commit**

```bash
git add functions/blob_to_search/pdf_text.py functions/blob_to_search/blob_io.py functions/blob_to_search/search_index.py
git commit -m "feat(blob-demo): add blob, pdf, and search data-plane wrappers"
```

---

### Task 5: Function app entry (both triggers) and project files

**Files:**
- Create: `functions/blob_to_search/function_app.py`
- Create: `functions/blob_to_search/host.json`
- Create: `functions/blob_to_search/requirements.txt`
- Create: `functions/blob_to_search/.funcignore`
- Modify: `.gitignore` (append function-local ignores)

**Interfaces:**
- Consumes: `func_config.load_config`, `blob_io.download_blob`, `blob_io.upload_blob`, `pdf_text.extract_pages`, `search_index.ensure_index`, `search_index.upload_documents`, `chunking.build_documents`, `upload_page.render_form_html/render_result_html/render_error_html/validate_upload`.
- Produces: two Functions named `index` (Event Grid) and `upload` (HTTP `/api/upload`).

- [ ] **Step 1: Write `function_app.py`**

Create `functions/blob_to_search/function_app.py`:

```python
from __future__ import annotations

import logging

import azure.functions as func

import blob_io
import func_config
import pdf_text
import search_index
import upload_page
from chunking import build_documents

app = func.FunctionApp()
log = logging.getLogger("blob_to_search")


@app.event_grid_trigger(arg_name="event")
def index(event: func.EventGridEvent) -> None:
    cfg = func_config.load_config()
    subject = event.subject or ""
    # subject: /blobServices/default/containers/<container>/blobs/<path>
    if "/blobs/" not in subject:
        log.info("ignoring non-blob event: %s", subject)
        return
    prefix, blob_name = subject.split("/blobs/", 1)
    container = prefix.rsplit("/containers/", 1)[-1]
    if container != cfg.upload_container or not blob_name.lower().endswith(".pdf"):
        log.info("skip %s/%s", container, blob_name)
        return
    data = blob_io.download_blob(cfg.storage_blob_endpoint, container, blob_name)
    pages = pdf_text.extract_pages(data)
    docs = build_documents(blob_name, pages, cfg.chunk_size)
    if not docs:
        log.warning("no extractable text in %s", blob_name)
        return
    search_index.ensure_index(cfg.search_endpoint, cfg.index_name)
    count = search_index.upload_documents(cfg.search_endpoint, cfg.index_name, docs)
    log.info("indexed %d chunks from %s", count, blob_name)


@app.route(route="upload", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def upload(req: func.HttpRequest) -> func.HttpResponse:
    cfg = func_config.load_config()
    if req.method == "GET":
        return func.HttpResponse(upload_page.render_form_html(), mimetype="text/html")

    part = req.files.get("file") if req.files else None
    if part is None:
        return func.HttpResponse(
            upload_page.render_error_html("파일이 없습니다."),
            mimetype="text/html", status_code=400,
        )
    filename = part.filename or ""
    body = part.read()
    error = upload_page.validate_upload(filename, len(body), cfg.max_upload_mb)
    if error:
        return func.HttpResponse(
            upload_page.render_error_html(error),
            mimetype="text/html", status_code=400,
        )
    blob_io.upload_blob(cfg.storage_blob_endpoint, cfg.upload_container, filename, body)
    return func.HttpResponse(
        upload_page.render_result_html(filename), mimetype="text/html"
    )
```

- [ ] **Step 2: Write `host.json`**

Create `functions/blob_to_search/host.json`:

```json
{
  "version": "2.0",
  "logging": {
    "applicationInsights": {
      "samplingSettings": { "isEnabled": true, "excludedTypes": "Request" }
    }
  },
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
```

- [ ] **Step 3: Write `requirements.txt`**

Create `functions/blob_to_search/requirements.txt`:

```
azure-functions
azure-identity>=1.19
azure-search-documents>=11.6
azure-storage-blob>=12.20
pypdf>=4.0
```

- [ ] **Step 4: Write `.funcignore`**

Create `functions/blob_to_search/.funcignore`:

```
.git*
.venv
__pycache__
tests
local.settings.json
```

- [ ] **Step 5: Append function-local ignores to repo `.gitignore`**

Add these lines to the end of `.gitignore`:

```
# Azure Functions local state (blob-to-search demo)
functions/blob_to_search/local.settings.json
functions/blob_to_search/.venv/
functions/**/__pycache__/
```

- [ ] **Step 6: Syntax-check the entry module and validate host.json**

Run:
```bash
python -m py_compile functions/blob_to_search/function_app.py && \
python -c "import json; json.load(open('functions/blob_to_search/host.json')); print('host.json OK')"
```
Expected: `host.json OK`.

- [ ] **Step 7: Confirm the repo test suite still passes**

Run: `uv run pytest tests/test_blob_chunking.py tests/test_blob_upload_page.py tests/test_blob_config.py -v`
Expected: PASS (all tests from Tasks 1–3).

- [ ] **Step 8: Commit**

```bash
git add functions/blob_to_search/function_app.py functions/blob_to_search/host.json functions/blob_to_search/requirements.txt functions/blob_to_search/.funcignore .gitignore
git commit -m "feat(blob-demo): add function app entry with upload and index triggers"
```

---

### Task 6: Bicep — Function App module

**Files:**
- Create: `infra/modules/functionapp.bicep`

**Interfaces:**
- Consumes: nothing.
- Produces outputs: `name`, `id`, `principalId`, `defaultHostName`.

- [ ] **Step 1: Write the module**

Create `infra/modules/functionapp.bicep`:

```bicep
@description('Function App 이름 (전역 유니크)')
param name string
param location string
@description('Function 런타임 스토리지 겸 업로드 대상 기존 스토리지 계정 이름')
param storageAccountName string
@description('AI Search 엔드포인트 (https://<name>.search.windows.net)')
param searchEndpoint string
param searchIndexName string = 'demo-blob-index'
param uploadContainer string = 'pdfs'
param chunkSize int = 1000
param maxUploadMb int = 50

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

var storageKey = sa.listKeys().keys[0].value
var storageConn = 'DefaultEndpointsProtocol=https;AccountName=${sa.name};AccountKey=${storageKey};EndpointSuffix=${environment().suffixes.storage}'
var blobEndpoint = 'https://${sa.name}.blob.${environment().suffixes.storage}'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${name}-plan'
  location: location
  kind: 'functionapp'
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true
  }
}

resource funcApp 'Microsoft.Web/sites@2023-12-01' = {
  name: name
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.12'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsStorage', value: storageConn }
        { name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING', value: storageConn }
        { name: 'WEBSITE_CONTENTSHARE', value: toLower(name) }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'ENABLE_ORYX_BUILD', value: 'true' }
        { name: 'SEARCH_ENDPOINT', value: searchEndpoint }
        { name: 'SEARCH_INDEX_NAME', value: searchIndexName }
        { name: 'STORAGE_BLOB_ENDPOINT', value: blobEndpoint }
        { name: 'UPLOAD_CONTAINER', value: uploadContainer }
        { name: 'CHUNK_SIZE', value: string(chunkSize) }
        { name: 'MAX_UPLOAD_MB', value: string(maxUploadMb) }
      ]
    }
  }
}

output name string = funcApp.name
output id string = funcApp.id
output principalId string = funcApp.identity.principalId
output defaultHostName string = funcApp.properties.defaultHostName
```

- [ ] **Step 2: Compile the module**

Run: `az bicep build --file infra/modules/functionapp.bicep --stdout > /dev/null && echo OK`
Expected: `OK` (warnings allowed, no errors).

- [ ] **Step 3: Commit**

```bash
git add infra/modules/functionapp.bicep
git commit -m "feat(blob-demo): add function app bicep module"
```

---

### Task 7: Bicep — RBAC module

**Files:**
- Create: `infra/modules/blobdemorbac.bicep`

**Interfaces:**
- Consumes: `functionPrincipalId` (from Task 6 output `principalId`), `storageAccountName`, `searchName`.
- Produces: three role assignments (no outputs).

- [ ] **Step 1: Write the module**

Create `infra/modules/blobdemorbac.bicep`:

```bicep
@description('Function App 시스템 관리 ID의 principalId')
param functionPrincipalId string
param storageAccountName string
param searchName string

var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchName
}

resource fnStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: sa
  name: guid(sa.id, functionPrincipalId, storageBlobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource fnSearchSvc 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, functionPrincipalId, searchServiceContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource fnSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, functionPrincipalId, searchIndexDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}
```

- [ ] **Step 2: Compile the module**

Run: `az bicep build --file infra/modules/blobdemorbac.bicep --stdout > /dev/null && echo OK`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add infra/modules/blobdemorbac.bicep
git commit -m "feat(blob-demo): add function identity rbac bicep module"
```

---

### Task 8: Bicep — top-level template, params, and pdfs container

**Files:**
- Create: `infra/blob-demo.bicep`
- Create: `infra/blob-demo.bicepparam`

**Interfaces:**
- Consumes: `infra/modules/functionapp.bicep`, `infra/modules/blobdemorbac.bicep`.
- Produces outputs: `functionAppName`, `functionAppId`, `functionHostName`, `uploadUrl`.

- [ ] **Step 1: Write the top-level template**

Create `infra/blob-demo.bicep`:

```bicep
targetScope = 'resourceGroup'

param location string = resourceGroup().location
@description('기존 스토리지 계정 이름 (pdfs 컨테이너 추가 + Function 런타임)')
param existingStorageAccountName string
@description('기존 AI Search 서비스 이름')
param existingSearchName string
param namePrefix string = 'blobsearch'
param suffix string = uniqueString(resourceGroup().id)
param uploadContainer string = 'pdfs'
param searchIndexName string = 'demo-blob-index'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: existingStorageAccountName
}
resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: sa
  name: 'default'
}
resource pdfs 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobSvc
  name: uploadContainer
  properties: {
    publicAccess: 'None'
  }
}

module fn 'modules/functionapp.bicep' = {
  name: 'blobdemo-func'
  params: {
    name: '${namePrefix}-${suffix}'
    location: location
    storageAccountName: existingStorageAccountName
    searchEndpoint: 'https://${existingSearchName}.search.windows.net'
    searchIndexName: searchIndexName
    uploadContainer: uploadContainer
  }
}

module rbac 'modules/blobdemorbac.bicep' = {
  name: 'blobdemo-rbac'
  params: {
    functionPrincipalId: fn.outputs.principalId
    storageAccountName: existingStorageAccountName
    searchName: existingSearchName
  }
}

output functionAppName string = fn.outputs.name
output functionAppId string = fn.outputs.id
output functionHostName string = fn.outputs.defaultHostName
output uploadUrl string = 'https://${fn.outputs.defaultHostName}/api/upload'
```

- [ ] **Step 2: Write the params file**

Create `infra/blob-demo.bicepparam`:

```bicep
using 'blob-demo.bicep'

param existingStorageAccountName = readEnvironmentVariable('UPLOAD_STORAGE_ACCOUNT', '')
param existingSearchName = readEnvironmentVariable('SEARCH_SERVICE_NAME', '')
```

- [ ] **Step 3: Compile the top-level template (also compiles both modules)**

Run: `az bicep build --file infra/blob-demo.bicep --stdout > /dev/null && echo OK`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add infra/blob-demo.bicep infra/blob-demo.bicepparam
git commit -m "feat(blob-demo): add top-level bicep with pdfs container"
```

---

### Task 9: Deploy and verify scripts

**Files:**
- Create: `scripts/deploy_blob_demo.sh`
- Create: `scripts/verify_blob_demo.py`

**Interfaces:**
- Consumes: `infra/blob-demo.bicep`, `infra/blob-demo.bicepparam`, `functions/blob_to_search/`.
- Produces: an executable deploy pipeline and an index document-count checker.

- [ ] **Step 1: Write the deploy script**

Create `scripts/deploy_blob_demo.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SUB="347e0df7-94e9-4feb-b42d-57d7e49566f2"
RG="rg-mirae-ai-agent-poc"
LOCATION="${LOCATION:-koreacentral}"
FUNC_DIR="functions/blob_to_search"

command -v func >/dev/null 2>&1 || {
  echo "Azure Functions Core Tools(func)가 필요합니다: npm i -g azure-functions-core-tools@4" >&2
  exit 1
}

az account set --subscription "$SUB"
az provider register --namespace Microsoft.EventGrid -o none || true

echo "== 기존 리소스 확인 =="
if [[ -z "${UPLOAD_STORAGE_ACCOUNT:-}" ]]; then
  ACCTS="$(az storage account list -g "$RG" --query "[].name" -o tsv)"
  COUNT="$(printf '%s\n' "$ACCTS" | grep -c . || true)"
  if [[ "$COUNT" != "1" ]]; then
    echo "스토리지 계정이 $COUNT개입니다. UPLOAD_STORAGE_ACCOUNT로 지정하세요:" >&2
    printf '%s\n' "$ACCTS" >&2
    exit 1
  fi
  UPLOAD_STORAGE_ACCOUNT="$(printf '%s\n' "$ACCTS" | head -1)"
fi
export UPLOAD_STORAGE_ACCOUNT
if [[ -z "${SEARCH_SERVICE_NAME:-}" ]]; then
  SEARCH_SERVICE_NAME="$(az search service list -g "$RG" --query "[0].name" -o tsv)"
fi
export SEARCH_SERVICE_NAME
echo "storage=$UPLOAD_STORAGE_ACCOUNT  search=$SEARCH_SERVICE_NAME"

SK="$(az storage account show -g "$RG" -n "$UPLOAD_STORAGE_ACCOUNT" --query allowSharedKeyAccess -o tsv)"
if [[ "$SK" == "false" ]]; then
  echo "경고: shared key 접근이 꺼져 있어 AzureWebJobsStorage(연결문자열)가 실패할 수 있습니다." >&2
  echo "필요 시: az storage account update -g $RG -n $UPLOAD_STORAGE_ACCOUNT --allow-shared-key-access true" >&2
fi

echo "== Bicep 배포 =="
az deployment group create \
  --resource-group "$RG" \
  --name blob-demo \
  --template-file infra/blob-demo.bicep \
  --parameters infra/blob-demo.bicepparam \
  --parameters location="$LOCATION" \
  -o none

FUNC_NAME="$(az deployment group show -g "$RG" -n blob-demo --query properties.outputs.functionAppName.value -o tsv)"
FUNC_ID="$(az deployment group show -g "$RG" -n blob-demo --query properties.outputs.functionAppId.value -o tsv)"
UPLOAD_URL="$(az deployment group show -g "$RG" -n blob-demo --query properties.outputs.uploadUrl.value -o tsv)"
echo "function=$FUNC_NAME"

echo "== 함수 코드 배포 (원격 빌드) =="
( cd "$FUNC_DIR" && func azure functionapp publish "$FUNC_NAME" --build remote )

echo "== Event Grid 구독 생성 =="
STORAGE_ID="$(az storage account show -g "$RG" -n "$UPLOAD_STORAGE_ACCOUNT" --query id -o tsv)"
az eventgrid event-subscription create \
  --name blob-to-search-demo \
  --source-resource-id "$STORAGE_ID" \
  --endpoint-type azurefunction \
  --endpoint "$FUNC_ID/functions/index" \
  --included-event-types Microsoft.Storage.BlobCreated \
  --subject-begins-with "/blobServices/default/containers/pdfs/" \
  -o none

echo ""
echo "== 완료 =="
echo "업로드 페이지: $UPLOAD_URL"
echo "CLI 업로드 예: az storage blob upload --account-name $UPLOAD_STORAGE_ACCOUNT --container pdfs --auth-mode login -f <sample.pdf> -n <sample.pdf>"
echo "인덱스 확인:  SEARCH_ENDPOINT=https://$SEARCH_SERVICE_NAME.search.windows.net uv run python scripts/verify_blob_demo.py"
```

- [ ] **Step 2: Write the verify script**

Create `scripts/verify_blob_demo.py`:

```python
"""demo-blob-index 문서 수를 출력한다. (관리 ID/개발자 자격증명 필요)"""
from __future__ import annotations

import os
import sys

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient


def main() -> int:
    endpoint = os.environ.get("SEARCH_ENDPOINT") or (
        sys.argv[1] if len(sys.argv) > 1 else ""
    )
    index = os.environ.get("SEARCH_INDEX_NAME", "demo-blob-index")
    if not endpoint:
        print("SEARCH_ENDPOINT를 환경변수나 첫 인자로 주세요.", file=sys.stderr)
        return 2
    client = SearchClient(
        endpoint=endpoint, index_name=index, credential=DefaultAzureCredential()
    )
    result = client.search(search_text="*", include_total_count=True, top=0)
    print(f"{index} 문서 수: {result.get_count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Make the deploy script executable and syntax-check both**

Run:
```bash
chmod +x scripts/deploy_blob_demo.sh && \
bash -n scripts/deploy_blob_demo.sh && \
python -m py_compile scripts/verify_blob_demo.py && echo OK
```
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy_blob_demo.sh scripts/verify_blob_demo.py
git commit -m "feat(blob-demo): add deploy and index-verify scripts"
```

---

### Task 10: Deploy to Azure and run the end-to-end demo

**Files:**
- None (execution task). Uses everything above.

**Interfaces:**
- Consumes: `scripts/deploy_blob_demo.sh`, `scripts/verify_blob_demo.py`.
- Produces: a live Function App, `pdfs` container, `demo-blob-index`, and Event Grid subscription.

- [ ] **Step 1: Ensure Azure login and tooling**

Run:
```bash
az account show >/dev/null 2>&1 || az login
az account set --subscription 347e0df7-94e9-4feb-b42d-57d7e49566f2
command -v func >/dev/null 2>&1 || npm i -g azure-functions-core-tools@4
```
Expected: an active subscription context and `func` available.

- [ ] **Step 2: Run the deploy script**

Run: `bash scripts/deploy_blob_demo.sh`
Expected: prints `storage=... search=...`, deploys Bicep, publishes the function (remote build succeeds), creates the Event Grid subscription, and prints the upload page URL. If it reports multiple storage accounts, re-run with `UPLOAD_STORAGE_ACCOUNT=<name> bash scripts/deploy_blob_demo.sh`.

- [ ] **Step 3: Capture a sample PDF**

Run:
```bash
cp "Docs/$(ls Docs | grep -i '\.pdf$' | head -1)" /tmp/blob_demo_sample.pdf && ls -la /tmp/blob_demo_sample.pdf
```
Expected: a PDF copied to `/tmp/blob_demo_sample.pdf`. (Any small PDF works.)

- [ ] **Step 4: Upload via the CLI (equivalent to the web page)**

Run:
```bash
ACCT="${UPLOAD_STORAGE_ACCOUNT:-$(az storage account list -g rg-mirae-ai-agent-poc --query "[0].name" -o tsv)}"
az storage blob upload --account-name "$ACCT" --container pdfs --auth-mode login \
  -f /tmp/blob_demo_sample.pdf -n blob_demo_sample.pdf --overwrite
```
Expected: upload succeeds (JSON with `lastModified`). This raises `BlobCreated` and triggers the `index` function.

- [ ] **Step 5: Wait, then verify documents landed in the index**

Run:
```bash
sleep 45
SEARCH_SVC="${SEARCH_SERVICE_NAME:-$(az search service list -g rg-mirae-ai-agent-poc --query "[0].name" -o tsv)}"
SEARCH_ENDPOINT="https://$SEARCH_SVC.search.windows.net" uv run python scripts/verify_blob_demo.py
```
Expected: `demo-blob-index 문서 수: <N>` where `N > 0`. If `0`, wait another 30–60s (cold start) and re-run; if still `0`, check `az functionapp log` / the function's Application Insights and confirm the Event Grid subscription exists via `az eventgrid event-subscription list --source-resource-id <storage-id>`.

- [ ] **Step 6: Verify the web upload page loads**

Run:
```bash
UPLOAD_URL="$(az deployment group show -g rg-mirae-ai-agent-poc -n blob-demo --query properties.outputs.uploadUrl.value -o tsv)"
echo "$UPLOAD_URL"
curl -sS -o /dev/null -w "%{http_code}\n" "$UPLOAD_URL"
```
Expected: prints the URL and HTTP `200`. Opening the URL in a browser shows the upload form; submitting a PDF there drives the same flow.

- [ ] **Step 7: Final commit (no-op safety) and summary**

Run: `git status --porcelain`
Expected: clean tree (all code already committed in Tasks 1–9). Report the upload URL and observed index document count to the user.

---

## Self-Review

**Spec coverage:**
- Reuse existing Storage + new `pdfs` container → Task 8 (container), Task 6/9 (runtime). ✓
- Reuse existing Search + new `demo-blob-index` → Task 4 (`build_index`), Task 5 (ensure). ✓
- Event Grid → Function direct → Task 9 (`--endpoint-type azurefunction`). ✓
- Python 3.12 / Y1 Linux / system MI → Task 6. ✓
- MI + RBAC only → Task 4 wrappers use `DefaultAzureCredential`; Task 7 grants roles. ✓
- pypdf extraction → Task 4. ✓
- Static 1000-char chunking → Task 1. ✓
- Idempotent overwrite → Task 1 (deterministic ids) + Task 4 (`merge_or_upload_documents`). ✓
- Upload web page (HTTP trigger, anonymous) → Task 2 + Task 5. ✓
- Storage Blob Data Contributor + Search Service/Index Data Contributor → Task 7. ✓
- Deploy end-to-end from one script → Task 9 + Task 10. ✓
- Unit test for chunking + validation → Tasks 1–3. ✓
- E2E via upload page / CLI + verify helper → Task 9/10. ✓
- Error handling (skip non-pdf, empty text, reject oversized upload) → Task 1/2/5. ✓

**Placeholder scan:** No TBD/TODO; every code and command step is complete. ✓

**Type consistency:** `load_config` fields used consistently in `function_app.py`; `build_documents` doc keys match `build_index` fields (`id, content, source_file, chunk_index, page, uploaded_at`); `principalId` output (Task 6) feeds `functionPrincipalId` (Task 7); function name `index` matches the Event Grid `--endpoint .../functions/index`. ✓
