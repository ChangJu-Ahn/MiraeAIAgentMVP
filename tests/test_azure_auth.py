import pytest
from azure.core.credentials import AzureKeyCredential
from config.settings import get_settings


@pytest.fixture(autouse=True)
def settings_cache(monkeypatch):
    for key in ("AZURE_AUTH_MODE", "SEARCH_API_KEY", "DOC_INTELLIGENCE_API_KEY",
                "FOUNDRY_API_KEY", "STORAGE_CONNECTION_STRING"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_identity_authentication_remains_the_default():
    from config.azure_auth import service_credential
    identity = object()
    assert service_credential("search", lambda: identity) is identity


def test_key_mode_requires_the_service_key_without_identity_fallback(monkeypatch):
    from config.azure_auth import service_credential
    monkeypatch.setenv("AZURE_AUTH_MODE", "keys")
    with pytest.raises(ValueError, match="SEARCH_API_KEY"):
        service_credential("search", lambda: pytest.fail("must not fallback"))
    get_settings.cache_clear()
    monkeypatch.setenv("SEARCH_API_KEY", "test-key")
    assert isinstance(service_credential("search"), AzureKeyCredential)


def test_openai_key_mode_does_not_request_an_entra_token(monkeypatch):
    from config.azure_auth import openai_auth
    monkeypatch.setenv("AZURE_AUTH_MODE", "keys")
    monkeypatch.setenv("FOUNDRY_API_KEY", "test-key")
    assert openai_auth(lambda: pytest.fail("No token")) == {"api_key": "test-key"}
    assert "test-key" not in repr(get_settings())


def test_key_agent_uses_azure_v1_endpoint_and_keeps_the_selected_deployment(monkeypatch):
    from config.azure_auth import chat_client
    import agent_framework.openai
    monkeypatch.setenv("AZURE_AUTH_MODE", "keys")
    monkeypatch.setenv("FOUNDRY_API_KEY", "test-key")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/demo")
    calls = []
    monkeypatch.setattr(agent_framework.openai, "OpenAIChatClient", lambda **kw: calls.append(kw) or object())
    chat_client("reasoning", lambda **kw: pytest.fail("No project token client"))
    assert calls == [{
        "base_url": "https://example.services.ai.azure.com/openai/v1/",
        "model": "reasoning", "api_key": "test-key",
    }]


def test_contributor_demo_defaults_to_keys_and_has_no_role_assignment_deployment():
    from scripts.deploy_demo import parse_args, deployment_values
    args = parse_args(["--resource-group", "rg-demo", "--check"])
    assert args.auth_mode == "keys"
    assert deployment_values(args, "", "User")["authMode"]["value"] == "keys"


def test_blob_key_mode_does_not_use_default_identity(monkeypatch):
    from ingest import blob
    from config.settings import Settings
    settings = Settings(
        azure_auth_mode="keys",
        storage_blob_endpoint="https://example.blob.core.windows.net",
        ingest_api_endpoint="https://function.azurewebsites.net",
        storage_connection_string="DefaultEndpointsProtocol=https;AccountName=example;AccountKey=test",
    )
    monkeypatch.setattr(blob, "get_settings", lambda: settings)
    import config.azure_auth
    monkeypatch.setattr(config.azure_auth, "get_settings", lambda: settings)
    from unittest.mock import MagicMock
    service = MagicMock()
    monkeypatch.setattr(blob.BlobServiceClient, "from_connection_string", lambda value: service)
    monkeypatch.setattr(blob, "DefaultAzureCredential", lambda: pytest.fail("No identity in key mode"))
    assert blob.BlobStore().service is service


def test_key_demo_templates_gate_rbac_and_do_not_output_service_keys():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    main = (root / "infra/main.bicep").read_text()
    assert "module rbac 'modules/rbac.bicep' = if (useManagedIdentity)" in main
    assert "module apprbac 'modules/apprbac.bicep' = if (useManagedIdentity)" in main
    ingestion = (root / "infra/ingestion.bicep").read_text()
    assert "module rbac 'modules/ingestion-rbac.bicep' = if (authMode == 'identity')" in ingestion
    chat = (root / "infra/customer-chat.bicep").read_text()
    assert "secretRef: 'search-key'" in chat and "secretRef: 'foundry-key'" in chat
    for path in (root / "infra").glob("customer-*.bicep"):
        assert all("listKeys" not in line and "listAdminKeys" not in line and "listCredentials" not in line
                   for line in path.read_text().splitlines() if line.startswith("output "))


def test_evaluation_key_mode_uses_the_configured_key_without_a_token_credential(monkeypatch):
    from eval import runner
    monkeypatch.setenv("AZURE_AUTH_MODE", "keys")
    monkeypatch.setenv("FOUNDRY_API_KEY", "test-key")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/demo")
    monkeypatch.setattr(runner, "DefaultAzureCredential", lambda: pytest.fail("No token credential"))
    model, credential = runner._judge()
    assert model["api_key"] == "test-key" and credential is None
