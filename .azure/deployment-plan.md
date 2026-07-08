# Azure Deployment Plan — MiraeAIAgentMVP (Chainlit → Azure Container Apps)

Status: Pending Approval (Phase 1 complete)

## 1. Goal
- Chainlit 기금운용평가 AI 챗봇을 **Azure Container Apps(ACA)** 에 **퍼블릭(익명)** 으로 배포.
- 데이터소스 원본 PDF **5개**를 **Blob Storage(공개 읽기)** 에 올리고, 화면에서 사용자가 원본을 열람.

## 2. Mode & Recipe
- MODE: **MODIFY** — 기존 손수작성 Bicep(`infra/`) 확장.
- RECIPE: **Bicep** (기존 IaC와 일관). 배포는 azure-validate → azure-deploy(`az deployment group create` + 컨테이너 빌드/푸시 + blob 업로드).

## 3. Reuse (기존, 재프로비저닝 안 함)
- `rg-mirae-ai-agent-poc` (koreacentral)의 AI Search / Document Intelligence / Foundry / App Insights.
- AI Search 인덱스에는 이미 5개 문서가 적재됨(멀티-연도 메타 필터 포함). ACA 앱은 이를 **질의만** 함(인제스트는 로컬 수동 CLI 유지).

## 4. Decisions (승인됨)
- 접근 제어: **완전 퍼블릭(익명, 인증 없음)** — 비용 감수.
- PDF 열람: **공개 읽기 Blob 컨테이너 + 고정 링크**.
- 리전: **koreacentral**.

## 5. Architecture — 추가 리소스 (Bicep 모듈 신규)
| 리소스 | 모듈 | 용도 |
|---|---|---|
| User-Assigned Managed Identity | `identity.bicep` | ACA 앱 신원(키리스) |
| Azure Container Registry (Basic) | `acr.bicep` | 컨테이너 이미지 저장, UAMI AcrPull |
| Log Analytics + Container Apps Env | `containerenv.bicep` | ACA 실행 환경 |
| Container App (external ingress, port 8000) | `containerapp.bicep` | Chainlit 앱, UAMI 연결, min/max replica=1 |
| Storage Account + Blob container(public read) | `storage.bicep` | 원본 PDF 5개 |
| RBAC (UAMI 대상) | `rbac.bicep` 확장 | Search Index Data Reader, Cognitive Services User(Foundry·DI), AcrPull |

- 앱 env(Container App): `DOC_INTELLIGENCE_ENDPOINT`, `SEARCH_ENDPOINT`, `FOUNDRY_PROJECT_ENDPOINT`, 각 deployment 이름, `APPINSIGHTS_CONNECTION_STRING`, `AZURE_CLIENT_ID`(UAMI), `SOURCE_DOCS_BASE_URL`(blob 컨테이너 URL).
- 인증: 앱 코드 `DefaultAzureCredential` → ACA에서 UAMI 사용(`AZURE_CLIENT_ID` 주입).

## 6. App 변경
- **Dockerfile** (신규, 루트): python:3.12-slim + uv, 코드 + `Docs/`(show_source_page 원문 렌더용) 포함, `chainlit run app/chat.py --host 0.0.0.0 --port 8000`.
- **.dockerignore**: `.venv`, `.ingest_cache`(67MB+), `.git`, tests, reports 등 제외.
- **config/settings.py**: `source_docs_base_url: str = ""` 추가(공개 blob 베이스 URL).
- **원본 열람 UI**: `app/chat.py` `on_chat_start`에서 환영 메시지 상단에 "📎 원본 자료(데이터소스) 5건" 링크 블록 렌더(`SOURCE_DOCS_BASE_URL` + 파일명). 5개 PDF를 새 탭에서 열람.
  - (참고) Chainlit 헤더의 정적 `header_links`는 배포 시 결정되는 스토리지 URL을 못 담아, env 기반 링크 블록으로 대신함. 배치는 배포 후 조정 가능.

## 7. 배포 실행 단계 (azure-deploy 단계에서)
1. `az deployment group create`로 infra 확장 프로비저닝(UAMI/ACR/Storage/ACA env/RBAC).
2. `az storage blob upload-batch`로 `Docs/` 5개 PDF를 공개 컨테이너에 업로드.
3. 컨테이너 이미지 빌드 → ACR 푸시(`az acr build`).
4. Container App 이미지 갱신 → 퍼블릭 FQDN 확인.
5. 기능 검증(챗봇 응답 + 원본 링크 열람).

## 8. Security Notes
- 앱 익명 퍼블릭(사용자 요청). Foundry 호출 비용 노출 — 사용자 감수 확인됨.
- Blob 컨테이너 익명 읽기(공개자료). 그 외 데이터 평면은 키리스 RBAC.
- 시크릿 없음(연결문자열은 App Insights만, env로 주입).

## 9. Out of Scope
- 인제스트 파이프라인의 컨테이너화(로컬 수동 CLI 유지).
- 멀티 레플리카/세션 어피니티(MVP는 replica=1).
- show_source_page의 멀티-문서 렌더 개선(현재 2025 기준, 별도 과제).

## 10. Steps / Status
- [x] Phase 1 계획 확정
- [ ] 사용자 승인
- [ ] Phase 2: Dockerfile/.dockerignore, infra 모듈 6종, settings/UI 변경, 검증
- [ ] status → Ready for Validation → azure-validate → azure-deploy
