from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    doc_intelligence_endpoint: str = ""
    search_endpoint: str = ""
    search_index_narrative: str = "narrative-index"
    search_index_table: str = "table-index"
    foundry_project_endpoint: str = ""
    foundry_chat_deployment: str = "chat"
    foundry_embedding_deployment: str = "embedding"
    foundry_api_version: str = "2024-10-21"
    source_pdf_path: str = "Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf"


@lru_cache
def get_settings() -> Settings:
    return Settings()
