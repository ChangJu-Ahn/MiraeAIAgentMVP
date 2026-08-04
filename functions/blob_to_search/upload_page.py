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
