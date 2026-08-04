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
