from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from config.settings import get_settings


def _label(blob_name: str) -> str:
    """Blob 이름에서 라벨(예: '2025 보고서')을 파생. NFC 정규화 후 한글 매칭."""
    n = unicodedata.normalize("NFC", blob_name)
    m = re.search(r"(20\d{2})", n)
    year = m.group(1) if m else ""
    kind = "지침" if "지침" in n else "보고서"
    return f"{year} {kind}".strip()


def source_doc_links() -> list[tuple[str, str]]:
    """컨테이너의 원본 PDF들에 대해 단기 user-delegation SAS 링크를 만든다.

    비공개 Blob이므로 앱의 관리 ID로 사용자 위임 키를 발급해 읽기 전용 SAS URL을 생성.
    실제 Blob 목록을 조회해 이름을 그대로 사용(파일명 정규화 불일치 방지).
    스토리지 미설정/실패 시 빈 리스트(링크 미표시).
    """
    s = get_settings()
    if not s.storage_account_name:
        return []
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas

        account_url = f"https://{s.storage_account_name}.blob.core.windows.net"
        svc = BlobServiceClient(account_url, credential=DefaultAzureCredential())
        start = datetime.now(timezone.utc) - timedelta(minutes=5)
        expiry = datetime.now(timezone.utc) + timedelta(hours=6)
        udk = svc.get_user_delegation_key(start, expiry)
        container = svc.get_container_client(s.source_docs_container)

        links: list[tuple[str, str]] = []
        for blob in container.list_blobs():
            name = blob.name
            if not name.lower().endswith(".pdf"):
                continue
            sas = generate_blob_sas(
                account_name=s.storage_account_name,
                container_name=s.source_docs_container,
                blob_name=name,
                user_delegation_key=udk,
                permission=BlobSasPermissions(read=True),
                expiry=expiry,
                start=start,
            )
            url = f"{account_url}/{s.source_docs_container}/{quote(name)}?{sas}"
            links.append((_label(name), url))
        return sorted(links)
    except Exception:  # noqa: BLE001 - 링크 생성 실패는 치명적이지 않음
        return []
