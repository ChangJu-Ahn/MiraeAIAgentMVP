from __future__ import annotations

from dataclasses import dataclass
from html import escape
from urllib.parse import urlsplit

_PDF_SUFFIX = ".pdf"
_DEFAULT_EVENT_SUB = "blob-to-search-demo"
_PORTAL_BASE = "https://portal.azure.com/#@/resource"

_PAGE_CSS = """
  * { box-sizing: border-box; }
  body { margin: 0; background: #f5f7f8; color: #182026;
         font-family: "Noto Sans KR", sans-serif; }
  main { width: min(760px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0; }
  h1 { font-size: 1.6rem; }
  h2 { font-size: 1.15rem; margin: 30px 0 10px; }
  .card { background: #fff; border: 1px solid #d7dde1; border-radius: 10px;
          padding: 24px; }
  .card + .card { margin-top: 18px; }
  input[type=file] { display: block; margin: 16px 0; }
  button { background: #006b5f; color: #fff; border: 0; border-radius: 6px;
           padding: 10px 18px; font-weight: 700; cursor: pointer; }
  .msg { margin-top: 18px; }
  .ok { color: #006b5f; } .err { color: #b4231f; }
  a { color: #006b5f; }
  .diagram { overflow-x: auto; }
  .diagram svg { width: 100%; height: auto; min-width: 520px; }
  .cap { font-size: .86rem; color: #4a5a62; margin: 10px 0 0; }
  .meta { font-size: .86rem; color: #4a5a62; margin: 0 0 12px; }
  table.portal { width: 100%; border-collapse: collapse; font-size: .9rem; }
  table.portal th, table.portal td { text-align: left; padding: 9px 10px;
    border-bottom: 1px solid #e4e9ec; vertical-align: top; }
  table.portal th { color: #4a5a62; font-weight: 700; background: #f0f4f5; }
  table.portal code { background: #eef2f3; padding: 1px 5px; border-radius: 4px;
    font-size: .86em; }
  table.portal small { color: #78868d; }
"""


@dataclass(frozen=True)
class ResourceInfo:
    subscription_id: str
    resource_group: str
    function_app: str
    storage_account: str
    upload_container: str
    search_service: str
    search_index: str
    event_subscription: str
    storage_url: str
    search_url: str
    function_url: str
    resource_group_url: str


def _host_label(endpoint: str) -> str:
    host = urlsplit(endpoint).hostname or ""
    return host.split(".")[0] if host else ""


def _resource_url(subscription: str, resource_group: str, provider_path: str) -> str:
    if not (subscription and resource_group and provider_path):
        return ""
    rid = (
        f"/subscriptions/{subscription}/resourceGroups/{resource_group}"
        f"/providers/{provider_path}"
    )
    return f"{_PORTAL_BASE}{rid}/overview"


def build_resource_info(cfg, env: dict[str, str]) -> ResourceInfo:
    """Derive Azure resource identities and portal links from config + platform env.

    Uses only non-secret values (endpoints and App Service platform variables);
    no keys or credentials are read or exposed.
    """
    storage_account = _host_label(cfg.storage_blob_endpoint)
    search_service = _host_label(cfg.search_endpoint)
    function_app = env.get("WEBSITE_SITE_NAME", "")
    resource_group = env.get("WEBSITE_RESOURCE_GROUP", "")
    owner = env.get("WEBSITE_OWNER_NAME", "")
    subscription_id = owner.split("+", 1)[0] if owner else env.get(
        "AZURE_SUBSCRIPTION_ID", ""
    )
    event_subscription = env.get("EVENT_SUBSCRIPTION_NAME", _DEFAULT_EVENT_SUB)

    return ResourceInfo(
        subscription_id=subscription_id,
        resource_group=resource_group,
        function_app=function_app,
        storage_account=storage_account,
        upload_container=cfg.upload_container,
        search_service=search_service,
        search_index=cfg.index_name,
        event_subscription=event_subscription,
        storage_url=_resource_url(
            subscription_id, resource_group,
            f"Microsoft.Storage/storageAccounts/{storage_account}",
        ) if storage_account else "",
        search_url=_resource_url(
            subscription_id, resource_group,
            f"Microsoft.Search/searchServices/{search_service}",
        ) if search_service else "",
        function_url=_resource_url(
            subscription_id, resource_group,
            f"Microsoft.Web/sites/{function_app}",
        ) if function_app else "",
        resource_group_url=(
            f"{_PORTAL_BASE}/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}/overview"
            if subscription_id and resource_group else ""
        ),
    )


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


# --- Architecture diagram (inline SVG, no external assets) -------------------

_NODE_STYLE = {
    "client": ("#ffffff", "#9aa7ad"),
    "app": ("#ffffff", "#006b5f"),
    "data": ("#f2fbfa", "#0a7f74"),
    "event": ("#fff3e0", "#d98324"),
}


def _svg_node(x: int, y: int, title: str, subtitle: str, kind: str) -> str:
    fill, stroke = _NODE_STYLE[kind]
    cx = x + 100
    return (
        f'<rect x="{x}" y="{y}" width="200" height="64" rx="10" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        f'<text x="{cx}" y="{y + 27}" text-anchor="middle" '
        f'font-size="15" font-weight="700" fill="#182026">{escape(title)}</text>'
        f'<text x="{cx}" y="{y + 46}" text-anchor="middle" '
        f'font-size="12" fill="#5a6a72">{escape(subtitle)}</text>'
    )


def _svg_arrow(x1: int, y1: int, x2: int, y2: int) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="#5a6a72" stroke-width="1.6" marker-end="url(#ah)"/>'
    )


def render_architecture_svg(container: str, index: str) -> str:
    r1 = 28
    r2 = 180
    parts = [
        '<svg viewBox="0 0 720 260" role="img" '
        'aria-label="블롭-투-AI Search 아키텍처 흐름도">',
        '<defs><marker id="ah" markerWidth="9" markerHeight="9" refX="7" '
        'refY="3" orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L8,3 L0,6 Z" fill="#5a6a72"/></marker></defs>',
        # Row 1 (left to right): Browser -> upload Function -> Blob
        _svg_node(20, r1, "브라우저", "파일 선택·업로드", "client"),
        _svg_node(250, r1, "Function · upload", "HTTP 트리거", "app"),
        _svg_node(480, r1, "Blob 컨테이너", container, "data"),
        # Row 2 (right to left): Event Grid -> index Function -> AI Search
        _svg_node(480, r2, "Event Grid", "BlobCreated 이벤트", "event"),
        _svg_node(250, r2, "Function · index", "Event Grid 트리거", "app"),
        _svg_node(20, r2, "AI Search 인덱스", index, "data"),
        # Arrows
        _svg_arrow(220, r1 + 32, 250, r1 + 32),
        _svg_arrow(450, r1 + 32, 480, r1 + 32),
        _svg_arrow(580, r1 + 64, 580, r2 - 2),
        _svg_arrow(480, r2 + 32, 450, r2 + 32),
        _svg_arrow(250, r2 + 32, 220, r2 + 32),
        "</svg>",
    ]
    return "".join(parts)


def _architecture_card(container: str, index: str) -> str:
    return (
        "<h2>아키텍처</h2>"
        "<div class=\"card\">"
        f"<div class=\"diagram\">{render_architecture_svg(container, index)}</div>"
        "<p class=\"cap\">PDF 업로드 → Blob 저장 → 이벤트 발생 → "
        "Function 실행 → AI Search 인덱싱 <strong>(임베딩 없음, 정적 청킹)</strong></p>"
        "</div>"
    )


# --- Azure portal navigation table ------------------------------------------

def _res_cell(name: str, url: str, kind_label: str) -> str:
    safe_name = escape(name) if name else "—"
    link = (
        f'<a href="{escape(url, quote=True)}" target="_blank" '
        f'rel="noopener">{safe_name}</a>'
        if url and name else safe_name
    )
    return f"{link}<br><small>{escape(kind_label)}</small>"


def _portal_card(info: ResourceInfo) -> str:
    rg_link = (
        f'<a href="{escape(info.resource_group_url, quote=True)}" target="_blank" '
        f'rel="noopener">{escape(info.resource_group)}</a>'
        if info.resource_group_url and info.resource_group
        else escape(info.resource_group or "—")
    )
    sub = escape(info.subscription_id or "—")

    rows = [
        (
            "업로드 컨테이너",
            _res_cell(info.storage_account, info.storage_url, "스토리지 계정"),
            f"데이터 스토리지 → 컨테이너 → <code>{escape(info.upload_container)}</code>",
        ),
        (
            "이벤트 구독",
            _res_cell(info.storage_account, info.storage_url, "스토리지 계정"),
            f"이벤트 → 이벤트 구독 → <code>{escape(info.event_subscription)}</code>",
        ),
        (
            "Function 앱",
            _res_cell(info.function_app, info.function_url, "Function App"),
            "함수 → <code>index</code> · <code>upload</code>",
        ),
        (
            "AI Search 인덱스",
            _res_cell(info.search_service, info.search_url, "AI Search"),
            f"검색 관리 → 인덱스 → <code>{escape(info.search_index)}</code>",
        ),
    ]
    body_rows = "".join(
        f"<tr><td>{c}</td><td>{r}</td><td>{p}</td></tr>" for c, r, p in rows
    )
    return (
        "<h2>Azure 포털에서 찾기</h2>"
        "<div class=\"card\">"
        f"<p class=\"meta\">구독: <code>{sub}</code> · 리소스 그룹: {rg_link}</p>"
        "<table class=\"portal\"><thead><tr>"
        "<th>구성요소</th><th>Azure 리소스</th><th>포털에서 보는 위치</th>"
        "</tr></thead><tbody>"
        f"{body_rows}"
        "</tbody></table>"
        "<p class=\"cap\">리소스 이름을 누르면 Azure 포털의 해당 리소스로 이동합니다. "
        "이어서 위 경로를 따라가면 설정을 직접 확인할 수 있습니다.</p>"
        "</div>"
    )


def render_form_html(info: ResourceInfo | None = None) -> str:
    container = info.upload_container if info else "pdfs"
    index = info.search_index if info else "demo-blob-index"
    upload_card = (
        "<h1>PDF 업로드 데모</h1>"
        "<div class=\"card\">"
        "<p>PDF를 올리면 blob에 저장되고, 이벤트로 Function이 실행되어 "
        "AI Search 인덱스에 적재됩니다.</p>"
        "<form action=\"/api/upload\" method=\"post\" enctype=\"multipart/form-data\">"
        "<input type=\"file\" name=\"file\" accept=\"application/pdf\" required>"
        "<button type=\"submit\">업로드</button>"
        "</form></div>"
    )
    body = upload_card + _architecture_card(container, index)
    if info is not None:
        body += _portal_card(info)
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
