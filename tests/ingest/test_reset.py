from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_reset_requires_exact_endpoint_before_any_mutation(monkeypatch):
    from ingest import reset
    client = MagicMock()
    monkeypatch.setattr(reset, "get_settings", lambda: SimpleNamespace(
        search_endpoint="https://intended.search.windows.net",
    ))
    with pytest.raises(ValueError, match="endpoint"):
        reset.reset_all("https://wrong.search.windows.net", client=client, store=MagicMock())
    assert not client.mock_calls


def test_reset_recreates_five_indexes_retires_demo_and_clears_only_manifests(monkeypatch):
    from ingest import reset
    settings = SimpleNamespace(
        search_endpoint="https://intended.search.windows.net",
        search_index_narrative="narrative-index", search_index_table="table-index",
        search_index_figure="figure-index", search_index_catalog="fund-catalog-index",
        search_index_facts="evaluation-facts-index",
    )
    monkeypatch.setattr(reset, "get_settings", lambda: settings)
    client = MagicMock()
    store = MagicMock()
    store.assets.list_blobs.return_value = [SimpleNamespace(name="manifests/doc.json")]
    reset.reset_all(settings.search_endpoint, client=client, store=store)
    assert {c.args[0] for c in client.delete_index.call_args_list} == {
        "narrative-index", "table-index", "figure-index", "fund-catalog-index",
        "evaluation-facts-index", "demo-blob-index",
    }
    assert len(client.create_index.call_args_list) == 5
    store.assets.delete_blob.assert_called_once_with("manifests/doc.json")
    store.inputs.delete_blob.assert_not_called()
