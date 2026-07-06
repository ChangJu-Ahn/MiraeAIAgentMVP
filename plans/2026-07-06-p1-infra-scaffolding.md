# P1: Azure 인프라 프로비저닝 + 프로젝트 스캐폴딩 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bicep(IaC)으로 전용 리소스 그룹에 Document Intelligence · AI Search · Microsoft Foundry(LLM/임베딩)를 키리스(Managed Identity/RBAC)로 배포하고, Python 프로젝트 골격 + 설정 로더 + `.env` 자동 채움 + 각 서비스 연결 스모크 테스트까지 완성한다.

**Architecture:** `infra/`의 Bicep 모듈이 리소스별로 분리되고 `main.bicep`이 조합·RBAC 할당·출력을 담당. 배포 산출 출력을 스크립트가 `.env`로 기록. `config/`의 pydantic-settings 로더가 `.env`를 읽어 타입 세이프 설정을 제공. `scripts/smoke_test.py`가 `DefaultAzureCredential`로 세 서비스에 각각 인증·핑.

**Tech Stack:** Bicep, Azure CLI 2.83+, Python 3.12(uv 관리), pydantic-settings, azure-identity, azure-search-documents, azure-ai-documentintelligence, openai(Azure), pytest.

## Global Constraints

- 필수 Azure 서비스만 사용: Document Intelligence, AI Search, Microsoft Foundry(LLM+임베딩). (스펙 §1)
- 인증은 **Managed Identity / Entra ID RBAC (키리스)**. 리소스는 `disableLocalAuth`/`authOptions`로 키 인증 비활성 지향, 로컬은 `DefaultAzureCredential`. (스펙 §1 배포)
- 리소스 그룹: `rg-mirae-ai-agent-poc`, region 기본 `koreacentral`. (스펙 §1)
- 구독: `347e0df7-94e9-4feb-b42d-57d7e49566f2` (ME-MngEnvMCAP094463-changjuahn-1).
- AI Search는 agentic retrieval을 위해 **Basic 티어 이상 + 시맨틱 랭커 활성**. (스펙 §3)
- 최종 ACA 배포 전제 → 모든 설정은 환경변수 주입. (스펙 §1)
- Python 3.12 고정(uv). 시크릿·`.env`는 커밋 금지(`.gitignore`에 이미 포함).
- 모든 커밋 끝에 다음 트레일러 포함:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

---

## File Structure

- `pyproject.toml` — uv 프로젝트 정의, 의존성, Python 3.12 핀
- `.python-version` — `3.12`
- `.env.example` — 필요한 모든 환경변수 키(값 비움)
- `README.md` — 셋업/배포/스모크 절차
- `config/__init__.py` — 패키지 초기화
- `config/settings.py` — pydantic-settings 기반 `Settings` 로더
- `infra/main.bicep` — RG 스코프 오케스트레이터(모듈 호출 + RBAC + outputs)
- `infra/modules/search.bicep` — Azure AI Search
- `infra/modules/docintelligence.bicep` — Document Intelligence(FormRecognizer)
- `infra/modules/foundry.bicep` — Foundry(AIServices 계정 + 프로젝트 + 모델 배포)
- `infra/modules/rbac.bicep` — 역할 할당(개발자 + Search→Foundry)
- `infra/main.bicepparam` — 파라미터 값
- `scripts/deploy.sh` — 배포 + outputs → `.env` 기록
- `scripts/verify_availability.sh` — 리전/모델/티어 가용성 검증
- `scripts/smoke_test.py` — 세 서비스 연결 스모크 테스트
- `tests/test_settings.py` — 설정 로더 단위 테스트

---

## Task 1: 프로젝트 스캐폴딩 (uv + pyproject + Python 3.12)

**Files:**
- Create: `pyproject.toml`, `.python-version`, `README.md`

**Interfaces:**
- Produces: uv 가상환경(`.venv`), 설치된 의존성. 이후 모든 task는 `uv run ...`로 실행.

- [ ] **Step 1: Python 3.12 핀 파일 작성**

Create `.python-version`:
```
3.12
```

- [ ] **Step 2: pyproject.toml 작성**

Create `pyproject.toml`:
```toml
[project]
name = "mirae-ai-agent-mvp"
version = "0.1.0"
description = "문서 기반 Agentic RAG 챗봇 PoC (Azure)"
requires-python = ">=3.12,<3.13"
dependencies = [
    "pydantic-settings>=2.5",
    "azure-identity>=1.19",
    "azure-search-documents>=11.6",
    "azure-ai-documentintelligence>=1.0",
    "openai>=1.54",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: 가상환경 생성 및 의존성 설치**

Run: `uv sync`
Expected: `.venv` 생성, 의존성 설치 성공 (에러 없이 종료).

- [ ] **Step 4: 설치 검증**

Run: `uv run python -c "import azure.identity, azure.search.documents, azure.ai.documentintelligence, openai, pydantic_settings; print('ok')"`
Expected: `ok`

- [ ] **Step 5: README 초안 작성**

Create `README.md`:
```markdown
# Mirae AI Agent MVP (Agentic RAG 챗봇 PoC)

문서 기반 Agentic RAG 챗봇 데모. Azure Document Intelligence + AI Search(agentic retrieval) + Microsoft Foundry + Microsoft Agent Framework + Chainlit.

## 요구사항
- Python 3.12 (uv), Azure CLI 2.83+, Bicep
- Azure 구독 로그인: `az login`

## 셋업
```bash
uv sync
```

## 인프라 배포 (P1)
```bash
bash scripts/verify_availability.sh   # 리전/모델 가용성 확인
bash scripts/deploy.sh                # 배포 + .env 생성
uv run python scripts/smoke_test.py   # 연결 스모크 테스트
```

설계: `specs/2026-07-06-agentic-rag-chatbot-design.md`
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .python-version README.md uv.lock
git commit -m "chore: scaffold uv project (python 3.12) with azure deps

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: 설정 로더 (config/settings.py) + .env.example

**Files:**
- Create: `config/__init__.py`, `config/settings.py`, `.env.example`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` (pydantic BaseSettings). 필드:
  `doc_intelligence_endpoint: str`, `search_endpoint: str`, `search_index_narrative: str`, `search_index_table: str`, `foundry_project_endpoint: str`, `foundry_chat_deployment: str`, `foundry_embedding_deployment: str`, `foundry_api_version: str`.
  함수 `get_settings() -> Settings` (lru_cache).

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_settings.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: config 패키지 작성**

Create `config/__init__.py`:
```python
```

Create `config/settings.py`:
```python
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: .env.example 작성**

Create `.env.example`:
```
# Azure Document Intelligence
DOC_INTELLIGENCE_ENDPOINT=

# Azure AI Search
SEARCH_ENDPOINT=
SEARCH_INDEX_NARRATIVE=narrative-index
SEARCH_INDEX_TABLE=table-index

# Microsoft Foundry
FOUNDRY_PROJECT_ENDPOINT=
FOUNDRY_CHAT_DEPLOYMENT=chat
FOUNDRY_EMBEDDING_DEPLOYMENT=embedding
FOUNDRY_API_VERSION=2024-10-21
```

- [ ] **Step 6: Commit**

```bash
git add config/ tests/test_settings.py .env.example
git commit -m "feat: add pydantic settings loader and .env.example

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: 가용성 검증 스크립트 (리전/티어/모델)

**Files:**
- Create: `scripts/verify_availability.sh`

**Interfaces:**
- Produces: 배포 전 koreacentral에서 AI Search Basic+ / Document Intelligence / Foundry 채팅·임베딩 모델 가용성을 출력. 미지원 항목은 경고.

- [ ] **Step 1: 스크립트 작성**

Create `scripts/verify_availability.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

SUB="347e0df7-94e9-4feb-b42d-57d7e49566f2"
LOCATION="${LOCATION:-koreacentral}"
CHAT_MODEL="${CHAT_MODEL:-gpt-4o}"
EMBED_MODEL="${EMBED_MODEL:-text-embedding-3-large}"

az account set --subscription "$SUB"
echo "== Region: $LOCATION =="

echo "-- AI Search SKUs (need basic+) --"
az search service list-sku-mapping 2>/dev/null || true
az provider show --namespace Microsoft.Search \
  --query "resourceTypes[?resourceType=='searchServices'].locations" -o tsv \
  | tr ',' '\n' | grep -i "korea" || echo "WARN: Search may not list koreacentral"

echo "-- Cognitive Services (Document Intelligence 'FormRecognizer') --"
az cognitiveservices account list-skus --location "$LOCATION" --kind FormRecognizer \
  -o table 2>/dev/null || echo "WARN: FormRecognizer SKU query failed for $LOCATION"

echo "-- Foundry (AIServices) chat/embedding model availability --"
az cognitiveservices model list --location "$LOCATION" \
  --query "[?contains(model.name, '${CHAT_MODEL}') || contains(model.name, '${EMBED_MODEL}')].{name:model.name, version:model.version, sku:model.skus[0].name}" \
  -o table 2>/dev/null || echo "WARN: model list failed; check portal"

echo ""
echo "위 목록에 $CHAT_MODEL, $EMBED_MODEL 이 없으면 LOCATION 또는 모델명을 조정하세요."
```

- [ ] **Step 2: 실행 권한 부여 및 실행**

Run:
```bash
chmod +x scripts/verify_availability.sh && bash scripts/verify_availability.sh
```
Expected: koreacentral에 대한 Search/FormRecognizer/모델 목록 출력. `gpt-4o`·`text-embedding-3-large`가 목록에 보이면 진행. 안 보이면 출력된 대안 모델명/리전을 Task 4 파라미터에 반영.

- [ ] **Step 3: (조건부) 파라미터 조정 결정 기록**

가용 모델/리전 확인 결과를 `infra/main.bicepparam`(Task 4에서 생성)에서 사용할 값으로 메모. 예: koreacentral에 `gpt-4o` 미가용 시 `eastus2` + 확인된 모델로 변경.

- [ ] **Step 4: Commit**

```bash
git add scripts/verify_availability.sh
git commit -m "chore: add azure region/model availability verification script

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: Bicep — AI Search 모듈

**Files:**
- Create: `infra/modules/search.bicep`

**Interfaces:**
- Produces (module outputs): `searchEndpoint string`, `searchName string`, `searchPrincipalId string` (시스템 할당 관리 ID). agentic retrieval을 위해 Basic 티어·시맨틱 랭커·시스템 관리 ID 활성.

- [ ] **Step 1: search.bicep 작성**

Create `infra/modules/search.bicep`:
```bicep
@description('AI Search 이름 (전역 유니크)')
param name string
param location string
@allowed(['basic', 'standard', 'standard2'])
param sku string = 'basic'

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: name
  location: location
  sku: {
    name: sku
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    semanticSearch: 'standard'
    authOptions: null
    disableLocalAuth: true
  }
}

output searchEndpoint string = 'https://${search.name}.search.windows.net'
output searchName string = search.name
output searchPrincipalId string = search.identity.principalId
```

- [ ] **Step 2: 문법 검증**

Run: `az bicep build --file infra/modules/search.bicep --stdout > /dev/null && echo OK`
Expected: `OK` (경고는 허용, 에러 없어야 함)

- [ ] **Step 3: Commit**

```bash
git add infra/modules/search.bicep
git commit -m "feat(infra): add AI Search bicep module (basic tier, semantic, keyless)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: Bicep — Document Intelligence 모듈

**Files:**
- Create: `infra/modules/docintelligence.bicep`

**Interfaces:**
- Produces: `docIntelligenceEndpoint string`, `docIntelligenceName string`. 키리스: `disableLocalAuth: true`, `customSubDomainName` 설정(토큰 인증 필수 조건).

- [ ] **Step 1: docintelligence.bicep 작성**

Create `infra/modules/docintelligence.bicep`:
```bicep
@description('Document Intelligence(FormRecognizer) 계정 이름')
param name string
param location string

resource di 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: name
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

output docIntelligenceEndpoint string = di.properties.endpoint
output docIntelligenceName string = di.name
```

- [ ] **Step 2: 문법 검증**

Run: `az bicep build --file infra/modules/docintelligence.bicep --stdout > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add infra/modules/docintelligence.bicep
git commit -m "feat(infra): add Document Intelligence bicep module (keyless)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: Bicep — Foundry 모듈 (AIServices + 프로젝트 + 모델 배포)

**Files:**
- Create: `infra/modules/foundry.bicep`

**Interfaces:**
- Produces: `foundryEndpoint string`(계정 엔드포인트), `foundryProjectEndpoint string`, `foundryName string`, `chatDeploymentName string`, `embeddingDeploymentName string`. 계정 kind `AIServices`, `allowProjectManagement: true`, 키리스.

- [ ] **Step 1: foundry.bicep 작성**

Create `infra/modules/foundry.bicep`:
```bicep
@description('Foundry(AIServices) 계정 이름')
param name string
param location string
param projectName string = 'proj-mirae-poc'

param chatModelName string = 'gpt-4o'
param chatModelVersion string = '2024-08-06'
param chatDeploymentName string = 'chat'
param chatCapacity int = 20

param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'
param embeddingDeploymentName string = 'embedding'
param embeddingCapacity int = 50

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: name
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: name
    disableLocalAuth: true
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: account
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: account
  name: chatDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: chatCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: account
  name: embeddingDeploymentName
  dependsOn: [chat]
  sku: {
    name: 'Standard'
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
}

output foundryName string = account.name
output foundryEndpoint string = account.properties.endpoint
output foundryProjectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${projectName}'
output foundryPrincipalId string = account.identity.principalId
output chatDeploymentName string = chat.name
output embeddingDeploymentName string = embedding.name
```

- [ ] **Step 2: 문법 검증**

Run: `az bicep build --file infra/modules/foundry.bicep --stdout > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add infra/modules/foundry.bicep
git commit -m "feat(infra): add Foundry AIServices bicep module (project + chat/embedding deployments)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: Bicep — RBAC 모듈 (키리스 역할 할당)

**Files:**
- Create: `infra/modules/rbac.bicep`

**Interfaces:**
- Consumes: 개발자 objectId, Search 관리 ID principalId, Foundry 계정 리소스명(스코프용).
- Produces: 역할 할당(개발자 → Search/DI/Foundry 데이터 평면; Search MI → Foundry OpenAI). 출력 없음.
- 역할 정의 ID(고정 GUID):
  - Search Index Data Contributor: `8ebe5a00-799e-43f5-93ac-243d3dce84a7`
  - Search Service Contributor: `7ca78c08-252a-4471-8644-bb5ff32d4ba0`
  - Cognitive Services User: `a97b65f3-24c7-4388-baec-2e87135dc908`
  - Cognitive Services OpenAI User: `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`

- [ ] **Step 1: rbac.bicep 작성**

Create `infra/modules/rbac.bicep`:
```bicep
@description('개발자(현재 사용자) objectId')
param developerObjectId string
@description('Search 서비스 시스템 관리 ID principalId')
param searchPrincipalId string
param searchName string
param docIntelligenceName string
param foundryName string

var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var openAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchName
}
resource di 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: docIntelligenceName
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: foundryName
}

// 개발자 → Search 데이터/서비스
resource devSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, developerObjectId, searchIndexDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
    principalId: developerObjectId
    principalType: 'User'
  }
}
resource devSearchSvc 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, developerObjectId, searchServiceContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributor)
    principalId: developerObjectId
    principalType: 'User'
  }
}

// 개발자 → Document Intelligence
resource devDI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: di
  name: guid(di.id, developerObjectId, cognitiveServicesUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: developerObjectId
    principalType: 'User'
  }
}

// 개발자 → Foundry (OpenAI 데이터 평면)
resource devFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, developerObjectId, openAIUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAIUser)
    principalId: developerObjectId
    principalType: 'User'
  }
}

// Search 관리 ID → Foundry (agentic retrieval이 임베딩/LLM 호출)
resource searchToFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, searchPrincipalId, openAIUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAIUser)
    principalId: searchPrincipalId
    principalType: 'ServicePrincipal'
  }
}
```

- [ ] **Step 2: 문법 검증**

Run: `az bicep build --file infra/modules/rbac.bicep --stdout > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add infra/modules/rbac.bicep
git commit -m "feat(infra): add RBAC bicep module (keyless role assignments)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 8: Bicep — main.bicep 오케스트레이터 + 파라미터

**Files:**
- Create: `infra/main.bicep`, `infra/main.bicepparam`

**Interfaces:**
- Consumes: Task 4~7 모듈.
- Produces (deployment outputs): `docIntelligenceEndpoint`, `searchEndpoint`, `foundryProjectEndpoint`, `chatDeploymentName`, `embeddingDeploymentName`. 이 이름들은 Task 9 `deploy.sh`가 읽어 `.env`에 매핑.

- [ ] **Step 1: main.bicep 작성**

Create `infra/main.bicep`:
```bicep
targetScope = 'resourceGroup'

param location string = resourceGroup().location
@description('현재 개발자 objectId (az ad signed-in-user)')
param developerObjectId string
@description('리소스 이름 접미사(전역 유니크)')
param suffix string = uniqueString(resourceGroup().id)

param chatModelName string = 'gpt-4o'
param chatModelVersion string = '2024-08-06'
param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'

module search 'modules/search.bicep' = {
  name: 'search'
  params: {
    name: 'srch-mirae-${suffix}'
    location: location
    sku: 'basic'
  }
}

module di 'modules/docintelligence.bicep' = {
  name: 'docintelligence'
  params: {
    name: 'di-mirae-${suffix}'
    location: location
  }
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  params: {
    name: 'aif-mirae-${suffix}'
    location: location
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
  }
}

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  params: {
    developerObjectId: developerObjectId
    searchPrincipalId: search.outputs.searchPrincipalId
    searchName: search.outputs.searchName
    docIntelligenceName: di.outputs.docIntelligenceName
    foundryName: foundry.outputs.foundryName
  }
}

output docIntelligenceEndpoint string = di.outputs.docIntelligenceEndpoint
output searchEndpoint string = search.outputs.searchEndpoint
output foundryProjectEndpoint string = foundry.outputs.foundryProjectEndpoint
output chatDeploymentName string = foundry.outputs.chatDeploymentName
output embeddingDeploymentName string = foundry.outputs.embeddingDeploymentName
```

- [ ] **Step 2: main.bicepparam 작성**

Create `infra/main.bicepparam`:
```bicep
using 'main.bicep'

param developerObjectId = readEnvironmentVariable('DEVELOPER_OBJECT_ID', '')
```

- [ ] **Step 3: 문법 검증 + 빌드**

Run: `az bicep build --file infra/main.bicep --stdout > /dev/null && echo OK`
Expected: `OK` (모듈 참조 해석 성공)

- [ ] **Step 4: Commit**

```bash
git add infra/main.bicep infra/main.bicepparam
git commit -m "feat(infra): add main.bicep orchestrator and params

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 9: 배포 스크립트 (deploy.sh) + what-if 검증 + .env 생성

**Files:**
- Create: `scripts/deploy.sh`

**Interfaces:**
- Consumes: Task 8 deployment outputs.
- Produces: 배포된 리소스 + 루트 `.env` 파일(설정 로더가 읽는 키로 매핑).

- [ ] **Step 1: deploy.sh 작성**

Create `scripts/deploy.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

SUB="347e0df7-94e9-4feb-b42d-57d7e49566f2"
RG="rg-mirae-ai-agent-poc"
LOCATION="${LOCATION:-koreacentral}"

az account set --subscription "$SUB"

echo "== 리소스 그룹 생성 =="
az group create --name "$RG" --location "$LOCATION" -o none

echo "== 개발자 objectId 조회 =="
export DEVELOPER_OBJECT_ID="$(az ad signed-in-user show --query id -o tsv)"
echo "objectId=$DEVELOPER_OBJECT_ID"

echo "== what-if (변경 미리보기) =="
az deployment group what-if \
  --resource-group "$RG" \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters location="$LOCATION" developerObjectId="$DEVELOPER_OBJECT_ID" || true

echo "== 배포 =="
az deployment group create \
  --resource-group "$RG" \
  --name mirae-p1 \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters location="$LOCATION" developerObjectId="$DEVELOPER_OBJECT_ID" \
  -o none

echo "== outputs → .env =="
OUT="$(az deployment group show --resource-group "$RG" --name mirae-p1 --query properties.outputs -o json)"
di=$(echo "$OUT"    | python3 -c "import sys,json;print(json.load(sys.stdin)['docIntelligenceEndpoint']['value'])")
srch=$(echo "$OUT"  | python3 -c "import sys,json;print(json.load(sys.stdin)['searchEndpoint']['value'])")
proj=$(echo "$OUT"  | python3 -c "import sys,json;print(json.load(sys.stdin)['foundryProjectEndpoint']['value'])")
chat=$(echo "$OUT"  | python3 -c "import sys,json;print(json.load(sys.stdin)['chatDeploymentName']['value'])")
embed=$(echo "$OUT" | python3 -c "import sys,json;print(json.load(sys.stdin)['embeddingDeploymentName']['value'])")

cat > .env <<EOF
DOC_INTELLIGENCE_ENDPOINT=$di
SEARCH_ENDPOINT=$srch
SEARCH_INDEX_NARRATIVE=narrative-index
SEARCH_INDEX_TABLE=table-index
FOUNDRY_PROJECT_ENDPOINT=$proj
FOUNDRY_CHAT_DEPLOYMENT=$chat
FOUNDRY_EMBEDDING_DEPLOYMENT=$embed
FOUNDRY_API_VERSION=2024-10-21
EOF

echo "== .env 생성 완료 =="
cat .env
```

- [ ] **Step 2: 실행 권한 + 배포 실행**

Run:
```bash
chmod +x scripts/deploy.sh && bash scripts/deploy.sh
```
Expected: 리소스 그룹 생성 → what-if 출력 → 배포 성공(수 분 소요) → `.env` 생성·출력. 오류 시(모델 미가용 등) Task 3의 조정값을 `--parameters`로 추가하여 재실행.

- [ ] **Step 3: .env 존재·비어있지 않음 확인**

Run: `test -s .env && grep -q "FOUNDRY_PROJECT_ENDPOINT=https" .env && echo OK`
Expected: `OK`

- [ ] **Step 4: Commit (deploy.sh만; .env는 .gitignore로 제외)**

```bash
git add scripts/deploy.sh
git commit -m "feat(infra): add deploy script that provisions RG and writes .env

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 10: 연결 스모크 테스트 (scripts/smoke_test.py)

**Files:**
- Create: `scripts/smoke_test.py`

**Interfaces:**
- Consumes: `config.settings.get_settings()`, `DefaultAzureCredential`.
- Produces: 세 서비스 각각에 대해 PASS/FAIL 출력. 하나라도 실패 시 종료코드 1.

- [ ] **Step 1: smoke_test.py 작성**

Create `scripts/smoke_test.py`:
```python
"""P1 연결 스모크 테스트: DI / AI Search / Foundry 를 키리스로 핑."""
import sys

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
```

- [ ] **Step 2: 스모크 테스트 실행**

Run: `uv run python scripts/smoke_test.py`
Expected: `PASS: AI Search`, `PASS: Document Intelligence`, `PASS: Foundry` 3줄, 종료코드 0.
(권한 전파 지연으로 실패 시 1~5분 후 재실행. Foundry 엔드포인트 형식 문제 시 `FOUNDRY_PROJECT_ENDPOINT` 베이스가 `https://<account>.services.ai.azure.com` 인지 확인.)

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "test: add keyless connectivity smoke test for DI/Search/Foundry

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과

- **Spec coverage:** 필수 스택(DI/Search/Foundry) 프로비저닝(Task 4~8), 키리스 RBAC(Task 7), 단일 RG·리전(Task 9), 설정 주입/모델 교체성(Task 2), 리전 가용성 검증(Task 3), 스모크 검증(Task 10). ACA·ingest·agent·app·eval은 후속 플랜(P2~P5)에서 다룸 — P1 범위 명확.
- **Placeholder scan:** 모든 코드/명령 구체화됨. 조건부 조정(모델 미가용)은 실행 판단 지점으로 명시.
- **Type consistency:** `.env.example`·`Settings` 필드·`deploy.sh` 매핑·`smoke_test.py` 사용 키가 일치(DOC_INTELLIGENCE_ENDPOINT, SEARCH_ENDPOINT, FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_CHAT_DEPLOYMENT, FOUNDRY_EMBEDDING_DEPLOYMENT, FOUNDRY_API_VERSION). Bicep output 이름(docIntelligenceEndpoint/searchEndpoint/foundryProjectEndpoint/chatDeploymentName/embeddingDeploymentName)이 deploy.sh 파서와 일치.

## 후속 플랜 (별도 작성)
- **P2**: 인제스트 (DI 파싱→청킹→임베딩→AI Search 2인덱스 + Knowledge Agent)
- **P3**: 에이전트 (Microsoft Agent Framework 오케스트레이터 + 도구)
- **P4**: Chainlit UI
- **P5**: Foundry Evaluation + Golden Q&A
