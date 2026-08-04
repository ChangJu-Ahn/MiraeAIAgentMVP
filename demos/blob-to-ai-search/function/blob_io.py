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
