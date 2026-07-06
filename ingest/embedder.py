from __future__ import annotations

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from config.settings import get_settings

_SCOPE = "https://cognitiveservices.azure.com/.default"


def _client() -> tuple[AzureOpenAI, str]:
    s = get_settings()
    base = s.foundry_project_endpoint.split("/api/projects")[0]
    provider = get_bearer_token_provider(DefaultAzureCredential(), _SCOPE)
    client = AzureOpenAI(
        azure_endpoint=base,
        api_version=s.foundry_api_version,
        azure_ad_token_provider=provider,
    )
    return client, s.foundry_embedding_deployment


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    if not texts:
        return []
    client, deployment = _client()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(model=deployment, input=batch)
        vectors.extend(item.embedding for item in resp.data)
    return vectors
