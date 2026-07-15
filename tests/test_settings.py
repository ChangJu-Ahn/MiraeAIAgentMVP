from config.settings import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DOC_INTELLIGENCE_ENDPOINT", "https://di.example/")
    monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.example/")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://aif.example/")
    monkeypatch.setenv("FOUNDRY_CHAT_DEPLOYMENT", "chat")
    monkeypatch.setenv("FOUNDRY_EMBEDDING_DEPLOYMENT", "embedding")
    s = Settings()
    assert s.doc_intelligence_endpoint == "https://di.example/"


def test_settings_defaults(monkeypatch):
    for name in (
        "SEARCH_INDEX_NARRATIVE",
        "SEARCH_INDEX_TABLE",
        "FOUNDRY_API_VERSION",
        "FOUNDRY_CHAT_DEPLOYMENT",
        "FOUNDRY_EMBEDDING_DEPLOYMENT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOC_INTELLIGENCE_ENDPOINT", "https://di.example/")
    monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.example/")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://aif.example/")
    s = Settings(_env_file=None)
    assert s.search_index_narrative == "narrative-index"
    assert s.search_index_table == "table-index"
    assert s.foundry_api_version == "2024-10-21"
    assert s.foundry_chat_deployment == "chat"
    assert s.foundry_embedding_deployment == "embedding"


def test_settings_exclude_removed_source_doc_storage():
    assert "storage_account_name" not in Settings.model_fields
    assert "source_docs_container" not in Settings.model_fields
