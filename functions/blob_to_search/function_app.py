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
