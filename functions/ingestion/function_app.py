from __future__ import annotations

import json
import logging
import threading
from urllib.parse import quote

import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContentSettings

from config.settings import get_settings
from ingest.blob import BlobStore, document_metadata
from ingest.jobs import JobStore, enqueue_blob, process_next_job

app = func.FunctionApp()
log = logging.getLogger("document_ingestion")
_INGEST_SLOT = threading.Lock()


@app.event_grid_trigger(arg_name="event")
def index(event: func.EventGridEvent) -> None:
    settings = get_settings()
    prefix = f"/blobServices/default/containers/{settings.upload_container}/blobs/"
    subject = event.subject or ""
    if not subject.startswith(prefix) or not subject.lower().endswith(".pdf"):
        log.info("Ignoring non-source event %s", subject)
        return
    enqueue_blob(subject[len(prefix):])


@app.timer_trigger(schedule="*/5 * * * * *", arg_name="timer", run_on_startup=False, use_monitor=False)
def process_jobs(timer: func.TimerRequest) -> None:
    if not _INGEST_SLOT.acquire(blocking=False):
        return  # Jobs are durable; the next timer tick will pick them up.
    try:
        process_next_job()
    finally:
        _INGEST_SLOT.release()


_FORM = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>문서 인제스트</title><body>
<h1>PDF → 본문 · 표 · 그림 인덱싱</h1>
<p>등록된 기금 보고서는 기존 파일명으로 업로드하면 후처리 정보가 자동 적용됩니다.</p>
<form method="post" enctype="multipart/form-data">
<p><input type="file" name="file" accept=".pdf" required></p>
<p>새 문서 유형 <select name="doc_type"><option value="">자동 / 일반 문서</option>
<option value="report">기금 보고서</option><option value="guideline">기금 지침</option></select></p>
<p>회계연도 <input name="year" type="number" min="2000" max="2099"></p>
<button type="submit">업로드</button></form>
<p>업로드 완료와 인덱싱 완료는 다릅니다. 문서는 25쪽씩 분석하며 중단된 범위부터 재개합니다.</p>
<p><a href="/api/jobs">문서별 처리 단계 · 진행 상태 확인</a></p>
<p><a href="/api/documents">인덱싱 완료 문서 확인</a></p>
</body></html>"""


def _json(value: object, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(value, ensure_ascii=False), status_code=status,
        mimetype="application/json", headers={"Cache-Control": "no-store"},
    )


@app.route(route="upload", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def upload(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "GET":
        return func.HttpResponse(_FORM, mimetype="text/html")
    part = req.files.get("file") if req.files else None
    if part is None:
        return _json({"error": "PDF 파일이 필요합니다."}, 400)
    name = part.filename or ""
    body = part.read()
    if (not name.lower().endswith(".pdf") or "/" in name or "\\" in name
            or not body.startswith(b"%PDF-")):
        return _json({"error": "유효한 PDF 파일을 선택하세요."}, 400)
    if len(body) > get_settings().max_upload_mb * 1024 * 1024:
        return _json({"error": "파일이 업로드 제한을 초과합니다."}, 413)
    metadata = {
        key: req.form[key] for key in ("year", "doc_type", "fund_scale")
        if req.form.get(key)
    }
    try:
        document_metadata(name, metadata)
    except ValueError as exc:
        return _json({"error": str(exc)}, 400)
    BlobStore().source(name).upload_blob(
        body, overwrite=True, metadata=metadata,
        content_settings=ContentSettings(content_type="application/pdf"),
    )
    return _json({"status": "uploaded", "source_file": name, "status_url": "/api/jobs",
                  "message": "Blob 저장 완료. 인덱싱은 비동기로 실행됩니다."}, 202)


@app.route(route="jobs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def jobs(req: func.HttpRequest) -> func.HttpResponse:
    return _json([job.public_status() for job in JobStore().jobs()])


@app.route(route="documents", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def documents(req: func.HttpRequest) -> func.HttpResponse:
    fields = ("doc_id", "source_file", "source_url", "year", "doc_type", "chunks")
    return _json([{key: record[key] for key in fields} for record in BlobStore().documents()])


@app.route(route="documents/{doc_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def document(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data, name = BlobStore().read_source(req.route_params["doc_id"], req.params.get("version"))
    except ResourceNotFoundError:
        return _json({"error": "인덱싱 완료된 문서가 없습니다."}, 404)
    return func.HttpResponse(data, mimetype="application/pdf", headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(name, safe='')}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    })


@app.route(
    route="figures/{doc_id}/{version}/{figure_id}", methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def figure(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = BlobStore().read_figure(
            req.route_params["doc_id"], req.route_params["version"],
            req.route_params["figure_id"],
        )
    except ResourceNotFoundError:
        return _json({"error": "그림을 찾을 수 없습니다."}, 404)
    return func.HttpResponse(data, mimetype="image/png",
                             headers={"X-Content-Type-Options": "nosniff"})
