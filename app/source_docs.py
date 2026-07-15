from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from html import escape
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from ingest.corpus import CORPUS, CorpusDoc


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "Docs"


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    label: str
    path: Path

    @property
    def href(self) -> str:
        return f"/source-docs/{self.doc_id}"


def _normalized_filename(path: str | Path) -> str:
    return unicodedata.normalize("NFC", Path(path).name).casefold()


def _resolve_source_path(corpus_doc: CorpusDoc) -> Path | None:
    expected_name = _normalized_filename(corpus_doc.pdf)
    if not DOCS_DIR.is_dir():
        return None
    return next(
        (
            path
            for path in DOCS_DIR.iterdir()
            if path.is_file()
            and path.suffix.casefold() == ".pdf"
            and _normalized_filename(path) == expected_name
        ),
        None,
    )


def _source_label(corpus_doc: CorpusDoc) -> str:
    kind = "지침" if corpus_doc.doc_type == "guideline" else "보고서"
    return f"{corpus_doc.year} {kind}"


def source_documents() -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    for corpus_doc in CORPUS:
        path = _resolve_source_path(corpus_doc)
        if path is None:
            continue
        documents.append(
            SourceDocument(
                doc_id=corpus_doc.doc_id,
                label=_source_label(corpus_doc),
                path=path,
            )
        )
    return documents


def source_docs_page() -> HTMLResponse:
    documents = source_documents()
    rows = "".join(
        (
            '<li class="document">'
            f'<a href="{escape(document.href, quote=True)}" '
            'target="_blank" rel="noopener noreferrer">'
            f'<span class="document-label">{escape(document.label)}</span>'
            '<span class="document-action" aria-hidden="true">PDF 열기</span>'
            "</a></li>"
        )
        for document in documents
    )
    if not rows:
        rows = '<li class="empty">원본 PDF를 불러올 수 없습니다.</li>'

    body = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>원본자료 | 기금운용평가 챗봇</title>
  <style>
    :root {{
      color-scheme: light dark;
      --background: #f5f7f8;
      --surface: #ffffff;
      --border: #d7dde1;
      --text: #182026;
      --muted: #5a6872;
      --accent: #006b5f;
      --accent-soft: #e2f2ef;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --background: #111719;
        --surface: #192125;
        --border: #344148;
        --text: #edf3f5;
        --muted: #acb8be;
        --accent: #70d6c7;
        --accent-soft: #183d38;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--background);
      color: var(--text);
      font-family: "Pretendard Variable", "Noto Sans KR", sans-serif;
      letter-spacing: 0;
    }}
    main {{ width: min(760px, calc(100% - 32px)); margin: 0 auto; padding: 56px 0 72px; }}
    h1 {{ margin: 0; font-size: clamp(1.75rem, 4vw, 2.4rem); line-height: 1.2; }}
    .intro {{ margin: 14px 0 32px; color: var(--muted); line-height: 1.75; }}
    ul {{ margin: 0; padding: 0; list-style: none; border-top: 1px solid var(--border); }}
    .document {{ border-bottom: 1px solid var(--border); }}
    .document a {{
      display: flex;
      min-height: 68px;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      padding: 14px 4px;
      color: var(--text);
      text-decoration: none;
    }}
    .document a:hover .document-label,
    .document a:focus-visible .document-label {{ color: var(--accent); }}
    .document a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 4px; }}
    .document-label {{ font-weight: 700; transition: color 120ms ease; }}
    .document-action {{
      flex: 0 0 auto;
      padding: 6px 10px;
      border-radius: 6px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 700;
    }}
    .empty {{ padding: 20px 4px; color: var(--muted); }}
    .note {{ margin: 26px 0 0; color: var(--muted); font-size: 0.9rem; line-height: 1.65; }}
    @media (max-width: 480px) {{
      main {{ width: min(100% - 24px, 760px); padding-top: 36px; }}
      .document a {{ min-height: 64px; gap: 12px; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>원본자료</h1>
    <p class="intro">RAG에 등록된 원본 PDF {len(documents)}개입니다. 문서를 선택하면 브라우저의 PDF 뷰어에서 실제 파일이 열립니다.</p>
    <ul>{rows}</ul>
    <p class="note">답변의 출처 번호와 물리 페이지를 원본 PDF에서 함께 확인할 수 있습니다.</p>
  </main>
</body>
</html>"""
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


def source_document_response(doc_id: str) -> FileResponse:
    document = next(
        (document for document in source_documents() if document.doc_id == doc_id),
        None,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Source document not found")
    return FileResponse(
        document.path,
        media_type="application/pdf",
        filename=document.path.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )