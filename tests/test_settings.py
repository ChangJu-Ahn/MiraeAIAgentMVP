import os
from config.settings import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DOC_INTELLIGENCE_ENDPOINT", "https://di.example/")
    monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.example/")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://aif.example/")
    monkeypatch.setenv("FOUNDRY_CHAT_DEPLOYMENT", "chat")
    monkeypatch.setenv("FOUNDRY_EMBEDDING_DEPLOYMENT", "embedding")
    s = Settings()
    assert s.doc_intelligence_endpoint == "https://di.example/"
    assert s.search_index_narrative == "narrative-index"  # default
    assert s.search_index_table == "table-index"          # default
    assert s.foundry_api_version  # non-empty default
