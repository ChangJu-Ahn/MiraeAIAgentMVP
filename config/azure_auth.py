from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from urllib.parse import urlsplit

from config.settings import get_settings


def secret_value(name: str) -> str:
    secret = getattr(get_settings(), name)
    if secret is None or not secret.get_secret_value():
        raise ValueError(f"{name.upper()} is required in keys authentication mode")
    return secret.get_secret_value()


def service_credential(service: str, identity_factory=DefaultAzureCredential):
    if get_settings().azure_auth_mode == "identity":
        return identity_factory()
    return AzureKeyCredential(secret_value(f"{service}_api_key"))


def openai_auth(identity_factory=DefaultAzureCredential) -> dict:
    if get_settings().azure_auth_mode == "keys":
        return {"api_key": secret_value("foundry_api_key")}
    return {"azure_ad_token_provider": get_bearer_token_provider(
        identity_factory(), "https://cognitiveservices.azure.com/.default",
    )}


def chat_client(model: str, identity_factory, credential_factory=DefaultAzureCredential):
    settings = get_settings()
    if settings.azure_auth_mode == "keys":
        from agent_framework.openai import OpenAIChatClient
        endpoint = settings.foundry_project_endpoint.split("/api/projects")[0].rstrip("/")
        if urlsplit(endpoint).scheme != "https" or not urlsplit(endpoint).netloc:
            raise ValueError("A valid HTTPS FOUNDRY_PROJECT_ENDPOINT is required")
        return OpenAIChatClient(
            base_url=endpoint + "/openai/v1/",
            model=model, api_key=secret_value("foundry_api_key"),
        )
    return identity_factory(
        project_endpoint=settings.foundry_project_endpoint,
        model=model, credential=credential_factory(),
    )
