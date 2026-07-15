# Mirae AI Agent MVP

기금운용평가 보고서와 지침을 근거로 답하는 Microsoft Foundry 기반 Agentic RAG PoC입니다.

## 흐름

1. Azure Document Intelligence가 PDF의 본문, 표, 그림, 페이지 구조를 추출합니다.
2. 인제스트 파이프라인이 추출 결과를 검증하고 Azure AI Search의 4개 인덱스에 적재합니다.
3. Microsoft Agent Framework가 질문에 필요한 검색 도구를 선택해 답변하고, 자가 점검을 켠 경우 근거가 부족하면 보완 질의로 두 번째 agent run을 수행합니다.
4. Chainlit이 답변을 스트리밍하고 인용 출처와 요청된 표, 차트, 원문 페이지를 표시합니다.
5. 평가 파이프라인이 동일한 Foundry judge deployment로 답변과 실제 검색 근거의 다섯 품질 기준을 검증합니다.

## 기술 스택

### 애플리케이션 및 오픈소스

| 영역 | 기술 | 프로젝트 내 역할 |
|---|---|---|
| 언어·런타임 | Python 3.12, `asyncio` | 인제스트, 검색, 에이전트, 평가와 스트리밍 런타임 |
| 패키지·빌드 | Astral `uv`, `uv.lock` | 의존성 설치와 재현 가능한 잠금 파일 관리 |
| 에이전트 | Microsoft Agent Framework 1.10+, Pydantic Settings | Foundry 모델 연결, 세션, function-call 툴, 환경 설정 |
| 웹 UI | Chainlit 2.11+ | WebSocket 채팅, 토큰·추론 스트리밍, 설정, 툴 단계와 디버그 화면 |
| Azure SDK | Azure Identity, Azure AI Search SDK, Azure Document Intelligence SDK, OpenAI Python SDK | 관리 ID 인증, 검색·인덱싱, PDF 분석, 임베딩과 모델 호출 |
| 평가 | Azure AI Evaluation 1.17, OpenPyXL | Excel 질문지 실행과 다섯 품질 기준 평가 |
| 관측성 | OpenTelemetry, Azure Monitor OpenTelemetry Exporter | 인메모리 디버그 span과 Application Insights trace 전송 |
| 시각화 | Plotly, Pillow, Poppler (`pdftoppm`) | 표·차트 생성과 인용 PDF 페이지 이미지 렌더링 |
| 테스트 | pytest 8.3+ | 단위, 스트리밍, 검색, 인제스트, 평가 계약 테스트 |
| 컨테이너 | Docker, `python:3.12-slim` | 포트 8000에서 Chainlit 애플리케이션 실행 |

`pyproject.toml`에는 애플리케이션이 직접 사용하는 패키지만 선언하고, 운영 이미지는 `uv sync --frozen --no-dev --no-install-project`로 `uv.lock`과 동일하게 설치합니다.

### Foundry 모델

| 배포 | 모델·버전 | SKU·용량 | 용도 |
|---|---|---|---|
| `reasoning` | `gpt-5.4-mini` `2026-03-17` | GlobalStandard 2000 | ACA의 기본 답변 생성, 도구 선택과 추론 요약 |
| `chat` | `gpt-4o` `2024-11-20` | GlobalStandard 450 | 그림 이해, reflection 판정과 평가 |
| `embedding` | `text-embedding-3-large` v1 | Standard 50 | 3072차원 문서·질의 임베딩 |

모델은 Microsoft Foundry 프로젝트의 배포 이름으로 참조합니다. 로컬 기본값은 `config/settings.py`, 운영 매핑은 `infra/main.bicep`의 Container App 환경 변수에서 관리합니다.

### Azure 구성요소

| Azure 서비스 | 구성 | 역할 |
|---|---|---|
| Microsoft Foundry | AIServices S0, Foundry project, 모델 배포 3개 | 답변, reasoning, embedding, vision, reflection과 평가 |
| Azure AI Search | Basic, Semantic Ranker, 시스템 할당 ID | 4개 검색 인덱스의 BM25·벡터·semantic·OData 조회 |
| Azure AI Document Intelligence | S0 | PDF layout, 본문, 표, 그림과 페이지 구조 추출 |
| Azure Container Registry | Basic | `mirae-chat` 컨테이너 이미지 저장과 ACR remote build |
| Azure Container Apps | Managed Environment, 외부 ingress, 1 vCPU·2 GiB, 1 replica | Chainlit 애플리케이션과 WebSocket 트래픽 호스팅 |
| Azure Monitor | Application Insights, Log Analytics | Agent Framework trace, 애플리케이션·플랫폼 로그와 메트릭 |
| Managed Identities·Azure RBAC | Container App UAMI, Search 시스템 ID | 키 없이 Search, Foundry와 ACR에 최소 권한으로 접근 |
| Azure Resource Manager | Bicep resource-group deployment | 리소스, 모델, 역할 할당과 런타임 환경 변수를 선언적으로 배포 |

인프라는 `infra/main.bicep`과 모듈로 관리하며, ACR의 익명 pull과 Foundry 로컬 키 인증은 사용하지 않습니다. 운영 Container App에는 `DefaultAzureCredential`이 선택할 UAMI의 `AZURE_CLIENT_ID`와 Search, Foundry, Application Insights 설정만 주입합니다.

## Azure AI Search 인덱스 및 검색 전략

애플리케이션은 증거 검색용 벡터 인덱스 2개와 전체 모집단 조회 및 계산용 비벡터 인덱스 2개를 사용합니다. 기본 인덱스명은 `config/settings.py`에서 환경 변수로 바꿀 수 있습니다.

| 인덱스 | 환경 변수 | 문서 단위 | 역할 | 조회 방식 |
|---|---|---|---|---|
| `narrative-index` | `SEARCH_INDEX_NARRATIVE` | 표가 아닌 본문, 제목, 그림 설명 등의 청크 | 정성 평가, 총평, 권고, 제도 설명 등 서술형 근거 검색 | BM25 + HNSW 벡터 + Semantic Ranker |
| `table-index` | `SEARCH_INDEX_TABLE` | `chunk_type == "table"`인 표 청크 | 점수, 등급, 수치가 포함된 원문 표와 주변 문맥 검색 | BM25 + HNSW 벡터 + Semantic Ranker |
| `fund-catalog-index` | `SEARCH_INDEX_CATALOG` | 연도별 TOC의 기금 1개 | 평가 대상 전체 목록, 정식 기금명, 별칭, 소관부처, 페이지 범위 확인 | `search_text="*"` + OData 정확 필터 |
| `evaluation-facts-index` | `SEARCH_INDEX_FACTS` | 기금, 연도, 평가지표 또는 가감점별 정규화 팩트 1개 | 지표값, 점수, 등급, 가감점, 출처와 모집단 기반 결정적 집계 | `search_text="*"` + OData 정확 필터 + Python 계산 |

### 벡터 인덱스 스키마

`narrative-index`와 `table-index`는 같은 스키마를 사용하고, 인제스트 시 청크 유형에 따라 저장 위치만 나뉩니다.

| 필드 | 형식 및 속성 | 용도 |
|---|---|---|
| `id` | `Edm.String`, key | 청크 식별자 |
| `content` | `Edm.String`, searchable, `ko.lucene` | BM25 검색 및 답변 근거 본문 |
| `content_vector` | `Collection(Edm.Single)`, 3072차원, searchable, non-retrievable | `text-embedding-3-large` 임베딩의 HNSW 최근접 검색 |
| `section_path` | `Edm.String`, searchable, filterable | 문서 내 섹션 경로이자 Semantic Ranker의 title 필드 |
| `doc_id` | `Edm.String`, filterable | 원본 문서 식별자 |
| `chunk_type` | `Edm.String`, filterable, facetable | `narrative`, `table`, `figure` 등 청크 유형 |
| `doc_type` | `Edm.String`, filterable, facetable | `report` 또는 `guideline` |
| `fund_name`, `fund_id` | `Edm.String`, filterable, facetable | 기금명 및 안정적인 기금 식별자 |
| `fund_scale` | `Edm.String`, filterable, facetable | `대형중소형`, `대규모` 등 기금 규모 |
| `ministry` | `Edm.String`, filterable, facetable | 소관부처 |
| `year` | `Edm.Int32`, filterable, facetable | 회계연도 |
| `page_physical`, `page_printed` | `Edm.Int32`, filterable | PDF 물리 페이지와 인쇄 페이지 |

벡터 검색은 `hnsw` 알고리즘과 `hnsw-profile` 프로필을 사용합니다. Semantic Ranker 설정 `sem`은 `section_path`를 title, `content`를 content 우선 필드로 사용합니다.

### 구조화 인덱스 스키마

`fund-catalog-index`는 TOC를 권위 있는 모집단으로 사용합니다.

| 필드 그룹 | 필드 | 용도 |
|---|---|---|
| 식별 | `id`, `fund_id`, `doc_id`, `year`, `toc_order` | 문서 키, 논리 기금 ID, 연도 및 TOC 순서 |
| 명칭 | `canonical_name`, `aliases` | 정식 명칭과 별칭의 정확 일치 조회 |
| 분류 | `ministry`, `fund_scale` | 소관부처 및 규모 필터 |
| 페이지 | `start_page_printed`, `end_page_printed`, `start_page_physical`, `end_page_physical`, `source_page_physical` | 기금별 보고서 범위와 TOC 출처 |

`evaluation-facts-index`는 계산에 필요한 값을 정규화해 저장합니다.

| 필드 그룹 | 필드 | 용도 |
|---|---|---|
| 식별 | `id`, `fund_id`, `fund_name`, `doc_id`, `year`, `ministry` | 기금, 문서, 연도 범위 지정 |
| 지표 | `fact_type`, `metric_code`, `metric_name` | 일반 평가지표와 가감점 구분, 코드 또는 이름 조회 |
| 값 | `metric_value`, `unit`, `score`, `max_score`, `adjustment` | 지표값, 평가점수, 만점, 부호 있는 가감점 |
| 등급 | `pre_grade`, `final_grade`, `grade`, `grade_rank` | 사전/최종 등급과 결정적 정렬용 등급 순위 |
| 모집단 | `source_scope`, `population_scope` | 연간 종합표, 기금 상세, 평가완료 집합 등 집계 기준 |
| 출처 | `source_chunk_id`, `source_page_physical`, `source_section_path`, `source_text` | 원문 청크, 페이지, 섹션과 인용 텍스트 |

### 검색 및 집계 전략

서술형 본문과 표 검색은 다음 순서로 한 번의 Azure AI Search 요청에서 수행됩니다.

1. 사용자 질의를 Foundry의 `embedding` 배포로 임베딩합니다. 기본 모델은 `text-embedding-3-large`, 벡터 차원은 3072입니다.
2. 같은 질의를 `search_text`로 전달해 BM25 키워드 검색을 실행합니다.
3. 질의 벡터로 `content_vector`에 대해 HNSW 검색을 실행합니다. `k_nearest_neighbors`는 반환 개수와 같은 값이며 기본값은 5입니다.
4. Azure AI Search가 텍스트와 벡터 후보를 하이브리드로 결합한 뒤 Semantic Ranker 설정 `sem`으로 재정렬합니다.
5. `year`, `doc_type`, `fund_name`, `fund_scale`이 지정되면 OData `and` 필터를 함께 적용합니다.
6. 결과 점수는 `@search.reranker_score`를 우선 사용하고, 없으면 `@search.score`를 사용합니다. 각 결과는 섹션 경로와 물리 페이지를 포함한 `[출처 N]` 근거로 기록됩니다.

카탈로그와 평가 팩트는 의미 검색을 하지 않습니다. `search_text="*"`와 정확 OData 필터로 모든 페이지를 끝까지 읽은 후 Python에서 정렬, 합계, 집합 연산을 수행합니다. 이 경로는 top-k 검색 결과를 전체 모집단으로 오인하거나 LLM이 수치와 순위를 직접 계산하는 것을 방지합니다.

- 기금 목록은 TOC 순서와 정식 명칭으로 결정적으로 정렬합니다.
- 기금명은 정규화한 정식 명칭 또는 별칭과 정확히 일치시킵니다. 연도 없이 같은 `fund_id`가 여러 해에 있으면 최신 항목을 사용하고, 서로 다른 `fund_id`가 충돌하면 모호한 이름으로 처리합니다.
- 평가지표는 `metric_code` 또는 정규화된 `metric_name`으로 조회합니다. `가감점`, `조정`, `가점`, `감점`은 모두 `fact_type == "adjustment"`로 해석합니다.
- 순위와 분포를 계산하기 전에 TOC 수, 데이터 보유 수, 제외·누락 기금을 계산합니다. `population="evaluated"`는 연간 `overall_grade`가 존재하는 기금과 대상 지표 팩트의 교집합입니다.
- 요청한 연도와 문서 유형이 corpus manifest에 없으면 검색 범위를 다른 연도나 문서로 넓히지 않고, 자료 부재를 출처로 기록합니다.
- 카탈로그와 팩트 갱신은 새 문서를 검증하고 업로드 성공을 확인한 뒤에만 이전 stale 문서를 삭제합니다.

## 에이전트 툴

`agent/orchestrator.py`는 `make_search_tools()`의 검색·구조화 툴 7개와 `make_visual_tools()`의 시각화 툴 3개를 합쳐 총 10개 function-call 툴을 등록합니다. Agent Framework는 Python 타입 힌트와 docstring을 입력 스키마 및 description으로 사용합니다.

| 분류 | 툴 | 하는 일 | 주요 반환 또는 부작용 |
|---|---|---|---|
| 검색 | `search_narrative` | 보고서·지침의 서술형 본문을 하이브리드 검색 | 최대 5개 본문 근거와 `[출처 N]` |
| 검색 | `search_tables` | 표와 수치 문맥을 하이브리드 검색 | 최대 5개 표 근거와 `[출처 N]` |
| 구조화 | `list_funds` | 연도·소관부처별 평가 대상 전체 기금 조회 | TOC 순서 목록, 모집단 수, catalog 출처 |
| 구조화 | `resolve_fund` | 기금명 또는 별칭을 정식 기금 엔티티로 해석 | 정식 명칭, `fund_id`, 연도, 소관부처, 별칭 |
| 구조화 | `get_fund_evaluations` | 개별 기금의 점수·등급·가감점 팩트 조회 | 구조화 값과 fact 출처, 조건부 평가완료 모집단 순위 |
| 구조화 | `aggregate_evaluations` | 단일 연도의 기금 간 점수·등급 순위 집계 | 모집단·데이터 보유·누락 수와 상·하위 결과 |
| 구조화 | `fund_analytics` | 순위·분포·연도 비교·등급 변화·동일 등급 교집합 계산 | 전체 모집단 기반 Python 결정적 분석 |
| 시각화 | `make_table` | 확인된 정형 데이터를 표로 표시 | Chainlit 표 visual 추가 |
| 시각화 | `make_chart` | 확인된 수치의 추세·비교 차트를 표시 | Chainlit line 또는 bar chart visual 추가 |
| 시각화 | `show_source_page` | 인용한 PDF 물리 페이지를 이미지로 표시 | Chainlit 원문 페이지 visual 추가 |

모든 검색·구조화 툴 호출은 `tool`, 입력 요약, hit 수, OData 필터를 trace에 기록합니다. 구조화 툴의 출력은 reflection과 평가에 사용할 evidence에도 저장되고, 동일한 `source_chunk_id`는 하나의 인용 번호로 재사용됩니다.

### 검색 툴 입력

두 검색 툴은 같은 입력 계약을 사용합니다.

```text
search_narrative(query, year=None, doc_type=None, fund_name=None, fund_scale=None)
search_tables(query, year=None, doc_type=None, fund_name=None, fund_scale=None)
```

| 파라미터 | 형식 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `query` | `str` | 예 | 없음 | Azure AI Search에 전달할 한국어 검색 질의 |
| `year` | `int \| None` | 아니요 | `None` | 회계연도 필터. 질문에 연도가 있으면 에이전트가 채움 |
| `doc_type` | `str \| None` | 아니요 | `None` | `report`(보고서) 또는 `guideline`(지침) |
| `fund_name` | `str \| None` | 아니요 | `None` | 개별 기금 정식 명칭 필터 |
| `fund_scale` | `str \| None` | 아니요 | `None` | `대형중소형` 또는 `대규모` 등 문서 메타데이터의 규모 필터 |

`search_narrative`는 `narrative-index`, `search_tables`는 `table-index`를 사용합니다. 검색 결과가 없으면 `검색 결과 없음`을 반환합니다. 지정한 연도·문서 유형이 corpus에 없으면 검색 대신 manifest 기반 부재 메시지를 반환하고 대체 검색을 차단합니다.

### 구조화 툴 입력

#### `list_funds`

```text
list_funds(year, ministry=None)
```

| 파라미터 | 형식 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `year` | `int` | 예 | 없음 | 회계연도. 허용 범위는 2000~2099 |
| `ministry` | `str \| None` | 아니요 | `None` | 소관부처 정확 필터. 생략하면 해당 연도의 전체 기금 |

#### `resolve_fund`

```text
resolve_fund(name, year=None)
```

| 파라미터 | 형식 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `name` | `str` | 예 | 없음 | 정식 기금명 또는 별칭. 예: `사학연금기금` |
| `year` | `int \| None` | 아니요 | `None` | 회계연도. 지정 시 2000~2099, 생략 시 전체 연도에서 탐색 |

#### `get_fund_evaluations`

```text
get_fund_evaluations(fund_name, year, metric=None)
```

| 파라미터 | 형식 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `fund_name` | `str` | 예 | 없음 | `resolve_fund`로 확인한 정식 기금명 권장 |
| `year` | `int` | 예 | 없음 | 회계연도. 허용 범위는 2000~2099 |
| `metric` | `str \| None` | 아니요 | `None` | 지표 코드 또는 이름. 예: `overall_grade`, `자산운용 위험관리의 효율성`, `가감점`. 생략하면 전체 지표 |

`asset_management_performance`를 명시적으로 조회하면 `overall_grade`가 있는 평가완료 모집단과의 교집합에서 해당 기금의 순위도 함께 계산합니다. 모든 반환 팩트가 가감점이면 총 가감점도 합산합니다.

#### `aggregate_evaluations`

```text
aggregate_evaluations(year, metric=None, order="desc", limit=3, ministry=None, per_fund=False)
```

| 파라미터 | 형식 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `year` | `int` | 예 | 없음 | 회계연도. 허용 범위는 2000~2099 |
| `metric` | `str \| None` | 아니요 | `None` | 지표 코드 또는 이름. 생략하면 모든 순위 가능 팩트 |
| `order` | `str` | 아니요 | `desc` | `desc`는 높은 순, `asc`는 낮은 순 |
| `limit` | `int` | 아니요 | `3` | 반환할 결과 수. 허용 범위는 1~100 |
| `ministry` | `str \| None` | 아니요 | `None` | 소관부처 정확 필터 |
| `per_fund` | `bool` | 아니요 | `False` | `True`이면 전체 상·하위 대신 기금마다 최대 `limit`개 지표 반환 |

#### `fund_analytics`

```text
fund_analytics(operation, years, metric="overall_grade", population="metric",
			   grade=None, order="desc", limit=3, ministry=None)
```

| 파라미터 | 형식 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `operation` | enum | 예 | 없음 | `rank`, `distribution`, `compare_years`, `grade_changes`, `maintained_grade` 중 하나 |
| `years` | `list[int]` | 예 | 없음 | 분석 회계연도 목록. 각 연도는 2000~2099 |
| `metric` | `str` | 아니요 | `overall_grade` | 지표 코드 또는 이름. 계량 성과점수는 `asset_management_performance`, 비계량 합계는 `qualitative_total` |
| `population` | enum | 아니요 | `metric` | `metric`은 해당 지표의 고유 모집단, `evaluated`는 연간 종합등급 보유 기금과의 교집합 |
| `grade` | `str \| None` | 조건부 | `None` | `maintained_grade`에서 필수. `탁월`, `우수`, `양호`, `보통`, `미흡`, `아주미흡` 중 하나 |
| `order` | enum | 아니요 | `desc` | `rank`의 정렬 순서인 `asc` 또는 `desc` |
| `limit` | `int` | 아니요 | `3` | `rank` 결과 수. 허용 범위는 1~100 |
| `ministry` | `str \| None` | 아니요 | `None` | 소관부처 정확 필터 |

| `operation` | 연도 조건 | 계산 내용 |
|---|---|---|
| `rank` | 정확히 1개 연도 | 점수 또는 등급 순위 |
| `distribution` | 정확히 1개 연도 | 등급별 개수와 해당 기금 목록 |
| `compare_years` | 서로 다른 2개 이상 연도 | 모든 연도에 공통으로 존재하는 기금의 값과 첫해 대비 마지막 해 방향 |
| `grade_changes` | 서로 다른 정확히 2개 연도 | 등급 또는 값이 상승·하락한 기금만 반환 |
| `maintained_grade` | 서로 다른 2개 이상 연도 | 지정한 `grade`를 모든 연도에 유지한 기금의 교집합 |

### 시각화 툴 입력

시각화는 검색으로 확인한 실제 값만 사용합니다. 기본 답변에서는 만들지 않고, 사용자가 시각물을 요청하거나 여러 수치의 비교가 글보다 명확할 때만 사용합니다.

#### `make_table`

```text
make_table(title, columns_json, rows_json)
```

| 파라미터 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `title` | `str` | 예 | 표 제목 |
| `columns_json` | JSON `str` | 예 | 열 이름 배열. 예: `["등급", "개수"]` |
| `rows_json` | JSON `str` | 예 | 문자열 행 배열. 예: `[["탁월", "3"], ["우수", "5"]]` |

#### `make_chart`

```text
make_chart(title, chart_kind, x_label, y_label, x_json, series_json)
```

| 파라미터 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `title` | `str` | 예 | 차트 제목 |
| `chart_kind` | `str` | 예 | `line` 또는 `bar`. 그 외 값은 `bar`로 처리 |
| `x_label` | `str` | 예 | x축 이름 |
| `y_label` | `str` | 예 | y축 이름 |
| `x_json` | JSON `str` | 예 | x축 값 배열. 예: `["2023", "2024", "2025"]` |
| `series_json` | JSON `str` | 예 | `[{"name": "기금명", "y": [1.0, 2.0, 3.0]}]` 형식의 시리즈 배열 |

#### `show_source_page`

```text
show_source_page(page)
```

| 파라미터 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `page` | `int` | 예 | 검색 결과의 `page_physical` 값. 사용자가 원문을 직접 요청했을 때만 표시 |

### 툴 선택 규칙

- 정성 평가, 총평, 권고, 개선 여부는 `search_narrative`를 사용합니다.
- 원문 표나 수치 문맥 확인은 `search_tables`를 사용합니다.
- 개별 기금 질문은 먼저 `resolve_fund`로 엔티티를 확인합니다. 찾지 못하면 같은 연도의 `list_funds`로 전체 TOC를 확인하고, 목록에도 없을 때 평가 대상이 아니라고 답합니다.
- 전체, 각 기금, 상위, 하위, 순위, 가장 등의 질문은 구조화 툴을 먼저 사용합니다.
- 가감점 질문은 `get_fund_evaluations(..., metric="가감점")`을 사용합니다.
- 순위는 `fund_analytics(operation="rank")`, 분포는 `distribution`, 연도 비교는 `compare_years`, 변동은 `grade_changes`, 동일 등급 유지는 `maintained_grade`를 사용합니다.
- 특정 연도 전체 총평은 `overall_grade` 분포와 `asset_management_performance` 순위를 모두 조회합니다.
- 표와 차트는 답변 근거를 검색한 뒤에만 만들고, 원문 페이지 이미지는 사용자가 직접 요청한 경우에만 표시합니다.
- 모든 최종 답변은 검색 또는 구조화 팩트의 `[출처 N]`을 인용하며, 근거가 없으면 값을 추정하지 않습니다.

### 툴 조합 예시 5개

아래 화살표는 대표적인 function-call 순서입니다. 실제 실행에서는 근거가 부족하면 같은 검색 툴을 다른 하위 질의로 반복 호출할 수 있습니다.

#### 1. 개별 기금의 최종등급

> 질문: 2025회계연도 공무원연금기금의 최종등급은?

- 판정: 개별 기금, 특정 연도, 구조화된 `overall_grade` 조회입니다. 의미 검색이나 LLM 계산이 필요하지 않습니다.
- 호출: `resolve_fund(name="공무원연금기금", year=2025)` → `get_fund_evaluations(fund_name="공무원연금기금", year=2025, metric="overall_grade")`
- 조합 이유: 첫 호출로 별칭·오타 가능성을 제거하고 안정적인 기금 엔티티를 확인한 뒤, 두 번째 호출에서 정확한 등급과 fact 출처를 가져옵니다.

#### 2. 정성 총평, 수치 확인, 원문 페이지

> 질문: 2025회계연도 고용보험기금 종합의견 핵심 3가지를 요약하고 평가결과 총괄표 원문도 보여줘.

- 판정: `종합의견`은 서술형 검색, `평가결과 총괄표`는 표 검색, `원문도 보여줘`는 원문 이미지 요청입니다.
- 호출: `resolve_fund(name="고용보험기금", year=2025)` → `search_narrative(query="종합의견 강점 미흡점", year=2025, doc_type="report", fund_name="고용보험기금")` → `search_tables(query="평가결과 총괄표 점수 등급", year=2025, doc_type="report", fund_name="고용보험기금")` → `show_source_page(page=280)`
- 조합 이유: 서술 근거와 표의 수치·등급을 교차 확인해 요약하고, 선택한 출처의 `page_physical`을 마지막 툴에 전달합니다. 예시의 `280`은 검색 결과에서 얻은 물리 페이지입니다.

#### 3. 소관부처 모집단, 하위 순위, 표 시각화

> 질문: 2025년 고용노동부 소관 평가 대상 기금과 비계량 합계 하위 3개를 표로 보여줘.

- 판정: `평가 대상`은 카탈로그 전체 모집단, `하위 3개`는 단일 연도 결정적 순위, `표로`는 명시적 시각화 요청입니다.
- 호출: `list_funds(year=2025, ministry="고용노동부")` → `aggregate_evaluations(year=2025, metric="qualitative_total", order="asc", limit=3, ministry="고용노동부", per_fund=False)` → `make_table(title="2025년 고용노동부 비계량 합계 하위 3개", columns_json="[...]", rows_json="[...]")`
- 조합 이유: TOC 기준 전체 기금 수를 먼저 확정하고, 그 범위에서 누락 여부와 하위 순위를 계산한 뒤 실제 반환값만 표로 렌더링합니다.

#### 4. 평가완료 모집단의 상위 순위

> 질문: 2025회계연도 자산운용 성과점수 상위 3개와 전체 모집단·제외 기금을 알려줘.

- 판정: `상위`, `전체 모집단`, `제외 기금`이 있으므로 semantic top-k가 아니라 전체 팩트의 결정적 순위가 필요합니다.
- 호출: `list_funds(year=2025)` → `fund_analytics(operation="rank", years=[2025], metric="asset_management_performance", population="evaluated", order="desc", limit=3)`
- 조합 이유: 첫 호출은 TOC 기준 대상 수와 명단을 제공하고, 두 번째 호출은 `overall_grade` 보유 기금과 성과점수 팩트의 교집합에서 상위 3개, 데이터 보유 수, 제외·누락 기금을 계산합니다.

#### 5. 다년 공통 기금의 점수 추이 차트

> 질문: 2021·2022·2025회계연도 자산운용 성과점수의 공통 기금 추이를 선 차트로 보여줘.

- 판정: 여러 연도의 공통 기금 비교는 집합 교집합과 연도별 값 정렬이 필요하고, `선 차트`는 명시적 시각화 요청입니다.
- 호출: `fund_analytics(operation="compare_years", years=[2021, 2022, 2025], metric="asset_management_performance", population="evaluated", order="desc", limit=100)` → `make_chart(title="자산운용 성과점수 추이", chart_kind="line", x_label="회계연도", y_label="평가점수", x_json="[\"2021\", \"2022\", \"2025\"]", series_json="[...]")`
- 조합 이유: Python이 세 연도 모두에 존재하는 기금만 교집합으로 만들고 각 연도의 실제 점수를 반환합니다. 차트 툴은 이 결과를 그대로 x축과 시리즈로 변환하며, 누락 연도를 보간하거나 추정하지 않습니다.

## 준비

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Azure CLI 2.83 이상과 Bicep
- `az login`으로 인증된 Azure 구독

```bash
uv sync
```

## Azure 인프라

```bash
bash scripts/verify_availability.sh
bash scripts/deploy.sh
uv run python scripts/smoke_test.py
```

Bicep은 AI Search, Document Intelligence, Foundry, Application Insights, managed identity, ACR, Container Apps를 배포합니다. 애플리케이션은 `DefaultAzureCredential`과 managed identity를 사용합니다.

## 인제스트

```bash
# 전체 등록 코퍼스 검증: Azure Search 쓰기와 모델 호출 없음
uv run python -m ingest.run --all --validate-only

# 전체 등록 코퍼스 적재
uv run python -m ingest.run --all

# 등록된 문서 하나만 적재
uv run python -m ingest.run --doc-id <doc-id>
```

`--validate-only`는 파싱, 청킹, 카탈로그, 평가 팩트, 완전성 계약만 검사합니다. 실제 적재에서 그림 설명이 필요 없으면 `--no-figures`를 사용합니다. 문서 목록과 메타데이터는 `ingest/corpus.py`에서 관리합니다.

## 질의

```bash
# CLI
uv run python -m agent.ask "2022년 종합등급 분포를 알려줘"

# 웹 UI
uv run chainlit run app/chat.py -w
```

채팅마다 하나의 Agent Framework 세션을 재사용하므로 후속 질문의 대화 문맥은 유지됩니다. 각 메시지는 기본적으로 한 번 실행되며, 자가 점검을 활성화하고 근거가 부족할 때만 보완 질의로 두 번째 run을 수행합니다. 자료에 근거가 없으면 없다고 답합니다.

Chainlit 헤더의 `원본자료` 링크는 RAG에 등록된 5개 실제 PDF 목록을 표시합니다. 각 항목은 컨테이너 이미지에 포함된 manifest 문서만 안정적인 문서 ID로 열며, 요청 경로를 파일 경로로 직접 해석하지 않습니다.

## 평가

```bash
# Excel 계약만 확인
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713" --validate-only

# 일부 문항 실행
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713" --limit 3

# 전체 실행 또는 checkpoint 재개
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713"
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713" --resume

# 검토 완료한 batch artifact를 고객 공개용 스냅샷으로 발행
uv run python -m eval.publication \
	reports/eval-Chatbot_질문지리스트_20260713-deployed-v11-20260715.json \
	public/evaluation-data.json
```

Excel의 `질문`과 `정답` 열은 필수입니다. Groundedness, Relevance, Similarity, Coherence, Fluency를 1~5점으로 평가하며 3점 이상을 통과로 기록합니다. 결과는 `reports/`의 Markdown과 JSON에 저장됩니다.

Chainlit 헤더의 `Evaluation` 링크는 배포 이미지에 고정된 고객 공개용 스냅샷을 표시합니다. 질문, 검토 정답, 실제 답변, evaluator별 점수·통과 여부·판정 근거는 공개하지만, exact judge context, 검색 trace, OData filter, source payload는 포함하지 않습니다. 다섯 evaluator는 다섯 품질 기준을 뜻하며 서로 다른 judge 모델 다섯 개를 뜻하지 않습니다. 모두 스냅샷에 기록된 동일 judge deployment를 사용합니다.

우측 상단 설정의 `답변 평가`는 기본적으로 꺼져 있습니다. 활성화하면 답변 스트리밍과 출처 표시가 끝난 뒤 Groundedness, Relevance, Coherence, Fluency를 백그라운드에서 평가합니다. 질문이 공개 고객 평가셋과 정확히 일치해 검토 정답이 있을 때만 Similarity를 추가하며, 임의 질문에 합성 정답을 만들지 않습니다. 완료된 결과는 `답변 평가 보기` 버튼으로 우측 패널에서 다시 열 수 있습니다.

## 관측성과 검증

`APPINSIGHTS_CONNECTION_STRING`이 설정되면 Agent Framework trace를 Application Insights로 전송합니다. 미설정이면 계측을 구성하지 않습니다.

```bash
uv run pytest -q
uv lock --check
```

현재 단순화 설계는 `docs/superpowers/specs/2026-07-15-core-demo-simplification.md`에 있습니다.
