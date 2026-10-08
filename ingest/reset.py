from __future__ import annotations

import argparse

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient

from config.settings import get_settings
from ingest.blob import BlobStore
from ingest.indexer import build_index
from ingest.structured_indexer import build_catalog_index, build_facts_index


def reset_all(
    confirm_endpoint: str, *, client: SearchIndexClient | None = None,
    store: BlobStore | None = None,
) -> None:
    settings = get_settings()
    if (not settings.search_endpoint
            or confirm_endpoint.rstrip("/") != settings.search_endpoint.rstrip("/")):
        raise ValueError("Confirmation must match the configured Search endpoint exactly")
    store = store or BlobStore()
    client = client or SearchIndexClient(
        endpoint=settings.search_endpoint, credential=DefaultAzureCredential(),
    )
    indexes = [
        build_index(settings.search_index_narrative),
        build_index(settings.search_index_table),
        build_index(settings.search_index_figure),
        build_catalog_index(settings.search_index_catalog),
        build_facts_index(settings.search_index_facts),
    ]
    # Invalidate replay suppression first, even if a subsequent reset step fails.
    for blob in store.assets.list_blobs(name_starts_with="manifests/"):
        store.assets.delete_blob(blob.name)
    for name in [index.name for index in indexes] + ["demo-blob-index"]:
        try:
            client.delete_index(name)
        except ResourceNotFoundError:
            pass
    for index in indexes:
        client.create_index(index)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete/recreate five indexes and clear ingestion manifests; keep source PDFs.",
    )
    parser.add_argument("--confirm-endpoint", required=True)
    args = parser.parse_args()
    reset_all(args.confirm_endpoint)
    print("Five indexes recreated; demo index retired; re-upload PDFs to populate them.")


if __name__ == "__main__":
    main()
