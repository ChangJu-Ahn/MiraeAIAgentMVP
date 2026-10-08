from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
import threading
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient, BlobServiceClient, ContentSettings
from pydantic import BaseModel, Field

from config.settings import get_settings
from ingest.corpus import CORPUS
from ingest.run import run

log = logging.getLogger(__name__)
_DOC_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_VERSION = re.compile(r"^[a-f0-9]{64}$")


class DocumentMetadata(BaseModel):
    doc_id: str
    doc_type: Literal["report", "guideline", "document"] = "document"
    year: int | None = Field(default=None, ge=2000, le=2099)
    fund_scale: str | None = None
    expected_overall_grade_count: int | None = None
    expected_overall_grade_excluded_fund_ids: tuple[str, ...] = ()


def document_metadata(blob_name: str, metadata: dict[str, str]) -> DocumentMetadata:
    normalized = unicodedata.normalize("NFC", blob_name)
    known = next((d for d in CORPUS
                  if unicodedata.normalize("NFC", Path(d.pdf).name) == normalized), None)
    if known:
        for key in ("year", "doc_type", "fund_scale"):
            if metadata.get(key) and str(getattr(known, key)) != metadata[key]:
                raise ValueError(f"{key} conflicts with registered document {known.doc_id}")
        return DocumentMetadata.model_validate(known.model_dump())
    doc_id = "blob-" + hashlib.sha256(normalized.encode()).hexdigest()[:32]
    result = DocumentMetadata(
        doc_id=doc_id, doc_type=metadata.get("doc_type") or "document",
        year=metadata.get("year") or None, fund_scale=metadata.get("fund_scale") or None,
    )
    if result.doc_type in {"report", "guideline"} and result.year is None:
        raise ValueError("year is required for report/guideline documents")
    return result


class BlobStore:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.storage_blob_endpoint or not settings.ingest_api_endpoint:
            raise ValueError("STORAGE_BLOB_ENDPOINT and INGEST_API_ENDPOINT are required")
        self.endpoint = settings.ingest_api_endpoint.rstrip("/")
        self.service = BlobServiceClient(
            settings.storage_blob_endpoint, credential=DefaultAzureCredential(),
        )
        self.inputs = self.service.get_container_client(settings.upload_container)
        self.assets = self.service.get_container_client(settings.assets_container)

    def source(self, name: str) -> BlobClient:
        return self.inputs.get_blob_client(name)

    def read_manifest(self, doc_id: str, version: str | None = None) -> dict | None:
        if not _DOC_ID.fullmatch(doc_id) or (version and not _VERSION.fullmatch(version)):
            return None
        name = f"versions/{doc_id}/{version}.json" if version else f"manifests/{doc_id}.json"
        try:
            return json.loads(self.assets.download_blob(name).readall())
        except ResourceNotFoundError:
            return None

    def write_manifest(self, doc_id: str, record: dict) -> None:
        data = json.dumps(record, ensure_ascii=False).encode()
        self.write_asset(f"versions/{doc_id}/{record['fingerprint']}.json", data, "application/json")
        self.write_asset(f"manifests/{doc_id}.json", data, "application/json")

    def has_pending(self, doc_id: str) -> bool:
        return self.assets.get_blob_client(f"pending/{doc_id}.json").exists()

    def write_pending(self, doc_id: str, fingerprint: str) -> None:
        self.write_asset(f"pending/{doc_id}.json",
                         json.dumps({"fingerprint": fingerprint}).encode(), "application/json")

    def clear_pending(self, doc_id: str) -> None:
        self.assets.delete_blob(f"pending/{doc_id}.json")

    def write_asset(self, name: str, data: bytes, content_type: str) -> None:
        self.assets.upload_blob(
            name, data, overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    def documents(self) -> list[dict]:
        records = [
            json.loads(self.assets.download_blob(blob.name).readall())
            for blob in self.assets.list_blobs(name_starts_with="manifests/")
            if blob.name.endswith(".json")
        ]
        return sorted(records, key=lambda d: d["source_file"])

    def read_source(self, doc_id: str, version: str | None = None) -> tuple[bytes, str]:
        record = self.read_manifest(doc_id, version)
        if record is None:
            raise ResourceNotFoundError("Document is not indexed")
        return self.assets.download_blob(record["original_asset"]).readall(), record["source_file"]

    def read_figure(self, doc_id: str, version: str, figure_id: str) -> bytes:
        record = self.read_manifest(doc_id, version)
        if record is None or record["fingerprint"] != version:
            raise ResourceNotFoundError("Figure version is not indexed")
        name = record["figures"].get(figure_id)
        if not name:
            raise ResourceNotFoundError("Unknown figure")
        return self.assets.download_blob(name).readall()


@contextmanager
def source_lease(source: BlobClient):
    """Serialize indexing for one source; a crashed worker's lease expires in 60s."""
    lease = source.acquire_lease(lease_duration=60)
    stop = threading.Event()
    failures: list[Exception] = []

    def renew() -> None:
        while not stop.wait(20):
            try:
                lease.renew()
            except Exception as exc:
                log.exception("Failed to renew source lease")
                failures.append(exc)
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield lease
        if failures:
            raise RuntimeError("Source lease lost during indexing") from failures[0]
    finally:
        stop.set()
        thread.join()
        lease.release()


def ingest_blob(blob_name: str, *, store: BlobStore | None = None) -> dict:
    if not blob_name.lower().endswith(".pdf"):
        raise ValueError("Only PDF sources are supported")
    store = store or BlobStore()
    source = store.source(blob_name)
    with source_lease(source) as lease:
        properties = source.get_blob_properties(lease=lease)
        metadata = document_metadata(blob_name, properties.metadata)
        content = source.download_blob(lease=lease).readall()
        if not content.startswith(b"%PDF-"):
            raise ValueError("Source is not a PDF")
        if len(content) > get_settings().max_upload_mb * 1024 * 1024:
            raise ValueError("Source exceeds MAX_UPLOAD_MB")
        fingerprint = hashlib.sha256(
            content + metadata.model_dump_json().encode() + b"layout-ingest-v1"
        ).hexdigest()
        previous = store.read_manifest(metadata.doc_id)
        if (previous and previous["fingerprint"] == fingerprint
                and not store.has_pending(metadata.doc_id)):
            log.info("Already indexed %s", blob_name)
            return previous
        if previous and (previous["doc_type"], previous["year"]) != (metadata.doc_type, metadata.year):
            raise ValueError("Use a new blob name when changing document type or year")

        prefix = f"documents/{metadata.doc_id}/{fingerprint}"
        original_asset = f"{prefix}/source.pdf"
        source_url = f"{store.endpoint}/api/documents/{quote(metadata.doc_id)}?version={fingerprint}"
        figures: dict[str, str] = {}

        def store_image(figure_id: str, png: bytes) -> str:
            asset = f"{prefix}/figures/{figure_id}.png"
            store.write_asset(asset, png, "image/png")
            figures[figure_id] = asset
            return f"{store.endpoint}/api/figures/{metadata.doc_id}/{fingerprint}/{figure_id}"

        store.write_pending(metadata.doc_id, fingerprint)
        store.write_asset(original_asset, content, "application/pdf")
        with tempfile.TemporaryDirectory(prefix="mirae-ingest-") as directory:
            root = Path(directory)
            pdf = root / "source.pdf"
            pdf.write_bytes(content)
            cache = root / "cache"
            cache.mkdir()
            count = run(
                str(pdf), metadata.doc_id, None, False,
                **metadata.model_dump(exclude={"doc_id"}),
                cache_dir=cache, source_file=blob_name, source_url=source_url,
                store_image=store_image,
            )
        # Re-reading with the lease fails if ownership was lost before publication.
        source.get_blob_properties(lease=lease)
        record = {
            **metadata.model_dump(mode="json"), "source_file": blob_name,
            "source_url": source_url, "fingerprint": fingerprint,
            "original_asset": original_asset, "figures": figures, "chunks": count,
        }
        store.write_manifest(metadata.doc_id, record)
        store.clear_pending(metadata.doc_id)
        log.info("Indexed %s: %d chunks, %d figures", blob_name, count, len(figures))
        return record
