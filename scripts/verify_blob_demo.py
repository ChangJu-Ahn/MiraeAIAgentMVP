"""demo-blob-index 문서 수를 출력한다. (관리 ID/개발자 자격증명 필요)"""
from __future__ import annotations

import os
import sys

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient


def main() -> int:
    endpoint = os.environ.get("SEARCH_ENDPOINT") or (
        sys.argv[1] if len(sys.argv) > 1 else ""
    )
    index = os.environ.get("SEARCH_INDEX_NAME", "demo-blob-index")
    if not endpoint:
        print("SEARCH_ENDPOINT를 환경변수나 첫 인자로 주세요.", file=sys.stderr)
        return 2
    client = SearchClient(
        endpoint=endpoint, index_name=index, credential=DefaultAzureCredential()
    )
    result = client.search(search_text="*", include_total_count=True, top=0)
    print(f"{index} 문서 수: {result.get_count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
