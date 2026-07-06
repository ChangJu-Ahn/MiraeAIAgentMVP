"""P1 연결 스모크 테스트: DI / AI Search / Foundry 를 키리스로 핑."""
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from azure.identity import DefaultAzureCredential
from config.settings import get_settings


def check_search(cred, s) -> None:
    from azure.search.documents.indexes import SearchIndexClient

    client = SearchIndexClient(endpoint=s.search_endpoint, credential=cred)
    list(client.list_index_names())  # 인증·연결 확인 (인덱스 0개여도 OK)


def check_doc_intelligence(cred, s) -> None:
    from azure.ai.documentintelligence import DocumentIntelligenceClient

    DocumentIntelligenceClient(endpoint=s.doc_intelligence_endpoint, credential=cred)
    # 클라이언트 생성 + 토큰 획득으로 엔드포인트/권한 확인
    cred.get_token("https://cognitiveservices.azure.com/.default")


def check_foundry(cred, s) -> None:
    from openai import AzureOpenAI

    token = cred.get_token("https://cognitiveservices.azure.com/.default")
    client = AzureOpenAI(
        azure_endpoint=s.foundry_project_endpoint.split("/api/projects")[0],
        api_version=s.foundry_api_version,
        azure_ad_token=token.token,
    )
    resp = client.embeddings.create(
        model=s.foundry_embedding_deployment, input="연결 테스트"
    )
    assert len(resp.data[0].embedding) > 0


def main() -> int:
    s = get_settings()
    cred = DefaultAzureCredential()
    checks = [
        ("AI Search", check_search),
        ("Document Intelligence", check_doc_intelligence),
        ("Foundry", check_foundry),
    ]
    failed = False
    for name, fn in checks:
        try:
            fn(cred, s)
            print(f"PASS: {name}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL: {name} -> {e}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
