# 수익자 홈페이지 AI 챗봇 PoC — Agentic RAG 챗봇 데모 설계

- **작성일**: 2026-07-06
- **상태**: 승인됨 (brainstorming)
- **원본 요구사항**: `Docs/수익자 홈페이지 AI 챗봇 개발 PoC 시나리오_v0.2.docx`
- **대상 데이터**: `Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf` (532p, 텍스트 레이어 존재)

## 1. 목표 & 스코프

### 목표
Microsoft & Azure AI 서비스를 기반으로, **오케스트레이션 가능하고 정량 평가되며 추론(생각) 절차를 관측할 수 있는** 문서 기반 Agentic RAG 챗봇을 고객 시연용 데모로 구현한다. 이 PoC의 근본 목적은 **Azure AI 서비스군의 검증**이다.

### 필수 기술 스택 (반드시 사용)
| 역할 | 서비스 |
|------|--------|
| 문서 파싱 / 레이아웃 / 마크다운 변환 | **Azure Document Intelligence** (prebuilt-layout) |
| 검색 엔진 + 벡터 DB | **Azure AI Search** (하이브리드 + Agentic Retrieval / Knowledge Agent) |
| LLM + 임베딩 모델 | **Microsoft Foundry** |
| 답변 평가 | **Microsoft Foundry Evaluation** |
| 에이전트 오케스트레이션 | **Microsoft Agent Framework** (GA, `agent-framework` Python) |
| UI | **Chainlit** (오픈소스) |
| 인프라 프로비저닝 | **Bicep** (전용 RG, Managed Identity RBAC) |
| 청킹 방법론 | 오픈소스 허용 |

### 포함 (In-scope)
- Azure DI Layout으로 PDF → 마크다운 (표·가로페이지 구조 보존)
- 레이아웃 인지 계층 청킹
- Azure AI Search 2개 인덱스 + 하이브리드 검색 + Agentic Retrieval (질문 분해·다중 조회·교차 참조)
- Microsoft Agent Framework 기반 오케스트레이터 에이전트 + 도구
- Chainlit UI: 단계별 추론(step) 표시, 표/차트 시각화, 근거 인용
- Foundry Evaluation: Golden Q&A + 5개 지표 리포트

### 제외 (Out-of-scope) — 사용자 확정
- 정형 Oracle DB 등 내부 시스템 연계 / 표→정형 DB 적재 (본 구축 2단계, 불필요)
- 완전 자동(노코드) 적재 파이프라인 — **사용자가 신규 PDF를 넣고 실행하는 수동 재실행 CLI로 충분**
- 비용/사용량 통제·모니터링 (불필요)
- 별도 대시보드 페이지 (답변 내 시각화로 대체)
- 사용자 인증 / RLS
- 홈페이지 UI 임베드
- 응답시간(5초) 실제 최적화 — 아래 "응답시간(설계 고려사항)"에 계획/설명만 포함

### 운영 방식
수동 실행 인제스트 CLI 1개로 구성. 지금은 PDF 1개(532p)로 인덱싱하고, 추가 자료(기금운용평가보고서·경영실적평가보고서·평가근거 자료 등)는 전달받는 대로 동일 CLI를 재실행하여 upsert한다.

### 배포 목표 & 인프라
최종적으로 **Azure Container Apps(ACA)** 배포 예정. 컨테이너화(Dockerfile)와 환경변수 기반 설정을 처음부터 전제로 설계한다.

- **프로비저닝**: **Bicep(IaC)** 로 전용 리소스 그룹 `rg-mirae-ai-agent-poc` (region `koreacentral`)에 DI · AI Search · Foundry(프로젝트/LLM/임베딩 배포)를 생성하고, 추후 ACA도 동일 RG에 배포하여 한곳에서 관리한다.
- **인증**: **Managed Identity / Entra ID RBAC (키리스)** 우선. 로컬 개발은 `DefaultAzureCredential`(Azure CLI 로그인), ACA는 시스템/사용자 할당 관리 ID. 필요한 RBAC(예: Search Index Data Contributor, Cognitive Services User, Foundry 접근)를 Bicep에서 함께 할당.
- ⚠️ **리전 가용성 검증 필요**: `koreacentral`은 AI Search **Agentic Retrieval(Knowledge Agent)** 및 일부 Foundry 모델 가용성이 제한될 수 있음 → 플랜 초기에 가용성 확인 단계 포함. 미지원 시 대체 리전(예: eastus2) 또는 해당 서비스만 별도 리전 배치.

## 2. 아키텍처 & 컴포넌트

```
┌─────────────────────────────────────────────────────────────┐
│  ingest/  (수동 재실행 파이프라인, CLI)                        │
│  PDF ─► Azure DI Layout ─► Markdown ─► 청킹 ─► 임베딩 ─► 인덱싱 │
│         (표·가로페이지 보존)  (섹션인지)  (Foundry) (AI Search) │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│  agent/  (Microsoft Agent Framework)                          │
│  분류 ─► Planner(분해) ─► Tool 루프(다단계) ─► 합성·인용       │
│    tools: agentic_search / table_lookup / cross_reference     │
└──────────────────────────────┬──────────────────────────────┘
                               │  (추론 step 스트리밍)
┌──────────────────────────────▼──────────────────────────────┐
│  app/  Chainlit UI — 채팅 + step 표시 + 표/차트 + 근거 카드    │
└───────────────────────────────────────────────────────────────┘
┌───────────────────────────────────────────────────────────────┐
│  eval/  Foundry Evaluation — Golden Q&A → 5개 지표 리포트       │
└───────────────────────────────────────────────────────────────┘
```

### 모듈 (각각 단독 실행·테스트 가능)
| 모듈 | 책임 | 핵심 의존성 |
|------|------|------------|
| `ingest/` | PDF→검색가능 인덱스. CLI 수동 실행, 파일 추가 시 재실행 | Azure DI, Foundry 임베딩, AI Search |
| `agent/` | 질문 분해·도구 선택·다단계 추론·답변 합성. UI와 분리된 순수 로직 | Agent Framework, Foundry LLM, AI Search |
| `app/` | Chainlit UI. agent 모듈 호출만 (step·시각화·인용 렌더) | Chainlit, agent 모듈 |
| `eval/` | Golden Q&A 실행 + Foundry Evaluation 지표 리포트 | Foundry Eval, agent 모듈 |
| `config/` | 설정 로더 (.env → Azure 엔드포인트·키·모델명 주입, 모델 교체성) | pydantic-settings 등 |

- **언어**: Python 3.11
- **설정 주입**: 모든 Azure 엔드포인트/키/모델명을 `config/` + `.env`로 주입 → 청킹·임베딩·LLM 모델 교체 가능 (V7 요구)

## 3. 인제스트 파이프라인 & 청킹 전략

### 파이프라인 (CLI, idempotent)
```
python -m ingest.run --pdf "Docs/....pdf"
  1) Azure DI (prebuilt-layout) → 마크다운 + 구조화 JSON
  2) 오프셋 보정: 인쇄 페이지번호("- 24 -") ↔ PDF 물리 페이지 매핑
  3) 레이아웃 인지 계층 청킹
  4) Foundry 임베딩 배치 계산
  5) AI Search 인덱스 upsert (문서ID 기반 idempotent)
```

### Azure Document Intelligence 최대 활용
단순 마크다운 변환을 넘어 DI가 제공하는 다음을 청킹·메타데이터에 반영한다:
- `paragraphs.role`: title / sectionHeading / pageHeader / **footnote** / pageNumber → 헤딩 계층·주석·페이지번호를 정규식 대신 DI 구조로 분리
- `sections` 계층 → `section_path` 자동 구성
- `tables`: 셀 span·행/열 헤더 → 표 구조화 (V1/V4)
- `figures`: 그림/차트 영역·캡션 추출
- `keyValuePairs`, reading order, 가로페이지 bounding region

### 청킹 전략 (채택: A — 레이아웃 인지 계층 청킹)
- DI 헤딩 계층(Ⅱ→1→가→ㅇ)을 파싱해 **섹션 단위**로 분할, 각 청크에 `section_path` 메타데이터 부여
- **표는 통째로 별도 청크**(분할 금지) + 표 캡션/주석 함께 보존 → 표 정확도
- 긴 섹션은 문단 경계로 재분할 (≈800~1000 토큰, 오버랩 15%)
- 청크 메타데이터: `doc_id`, `section_path`, `page_printed`, `page_physical`, `chunk_type`(narrative|table|figure), `year`, `fund_name`(추출 가능 시)

*대안 B(고정 크기+오버랩), C(시맨틱 청킹)는 표 손상·데모 차별성 약화로 미채택. 필요 시 config로 전환 가능하도록 청킹 전략을 인터페이스화.*

### 인덱스 구성 (N개 조합)
- `narrative-index`: 서술 본문 청크 (벡터 + BM25 + 시맨틱 재정렬)
- `table-index`: 표 청크 (셀 텍스트 + 표 요약 임베딩)
- 상위에 **AI Search Knowledge Agent (agentic retrieval)** — 질문을 서브쿼리로 분해해 두 인덱스를 병렬 조회·병합

## 4. 에이전트 오케스트레이션 (Microsoft Agent Framework)

단일 오케스트레이터 에이전트 + 도구 집합. 관측 가능한 다단계 추론.

```
사용자 질문
  └─► Orchestrator Agent (Foundry LLM, Agent Framework)
        ① 질문 유형 분류 (단일/표/다년도/교차참조/종합/원문부재)
        ② Planner: 서브쿼리 분해
        ③ Tool 호출 루프 (다단계):
            • agentic_search(query)    → AI Search Knowledge Agent (2 인덱스)
            • table_lookup(fund, year) → table-index 정밀 조회
            • cross_reference(claim)   → 근거 문서 연결 (V5)
        ④ 근거 취합 → 답변 합성 + 인용(citation) 부착
        ⑤ 할루시네이션 가드: 근거 없으면 "자료에 없음" 응답
        └─► 각 단계를 step 이벤트로 스트리밍 (Chainlit 표시)
```

- **추론 절차 가시화**: Agent Framework 미들웨어/이벤트로 계획·도구호출·중간판단을 step으로 방출 → UI 실시간 표시
- **멀티턴 메모리**: Agent Framework thread/session (최근 N턴)
- **가드레일**: 시스템 프롬프트 + 프롬프트 인젝션 필터 + 근거 없을 시 응답 거부
- **모델 교체성**: LLM/임베딩 모델명을 config로 주입

## 5. UI (Chainlit)
- 채팅 위젯 + **에이전트 step 실시간 표시** (계획·도구호출·중간판단 접기/펼치기)
- 답변 내 **표/차트 자동 렌더** (정형 질의 시 markdown 표 또는 plotly 차트)
- **근거 카드**: 인용 청크의 `section_path`·페이지·원문 스니펫
- 응답 토큰 스트리밍

## 6. 평가 (Foundry Evaluation)
- `eval/` CLI: Golden Q&A(초안 20~30문항, 6유형: 단일검색·표데이터·다년도·다중문서교차·종합요약·원문부재) → agent 실행 → 지표 리포트
- 지표: Groundedness / Relevance / Retrieval / Citation 정확도 / Coherence·Fluency
- 결과: 유형별 점수표 + 목표선(정확도 80% · 근거인용 90% · 할루시네이션 방어 90%) 대비 HTML/MD 리포트
- Golden Q&A는 AI가 초안 작성, MVP 개발 완료 후 사용자가 리뷰

## 7. 비기능 요구사항
| 유형 | 내용 |
|------|------|
| 응답 시간 | **설계 고려사항(구현 최적화는 범위 외, 사용자 확정)**: 실측 5~25초(에이전트 다단계 추론 + 도구 호출 + 평가 judge). 5초 목표 접근 방안 — ① 토큰 스트리밍으로 first-token 체감 단축, ② 도구 호출 병렬화, ③ 경량 judge/생략(런타임 경로에서 평가 제외), ④ 임베딩·검색 캐시, ⑤ 시맨틱 재정렬 top-k 축소. PoC는 정확도·관측성 우선이며 지연 최적화는 본 구축 단계 과제. |
| 관측 | **Azure Application Insights + OpenTelemetry (필수)**: Agent Framework 내장 계측으로 에이전트 실행·툴 콜(입력=근거, 출력=답변)·프롬프트를 gen_ai 스팬으로 기록(민감 데이터 포함). 진입점에서 `setup_observability()` 호출. |
| 가드레일 | 근거 없을 시 응답 거부(할루시네이션 방어, 구현·평가됨). 프롬프트 인젝션·민감정보 필터는 본 PoC 범위 외(개인정보 미포함). |
| 비용 통제 | 범위 외(사용자 확정). |
| 보안 | 키리스(Managed Identity/Entra ID RBAC). 키/엔드포인트·연결문자열은 `.env`/시크릿, 코드 커밋 금지. |

## 8. 프로젝트 구조
```
MiraeAIAgentMVP/
├── ingest/        # DI 파싱·청킹·임베딩·인덱싱 (CLI)
├── agent/         # Agent Framework 오케스트레이터·도구
├── app/           # Chainlit UI
├── eval/          # Golden Q&A + Foundry Evaluation
├── config/        # 설정 로더 (.env, 모델·엔드포인트)
├── infra/         # Bicep IaC (RG 리소스 + RBAC + 추후 ACA)
├── tests/         # 모듈별 단위 테스트
├── Docs/          # 원본 문서 (기존)
├── docs/          # 설계·플랜 문서
├── Dockerfile     # ACA 배포용
├── pyproject.toml
├── .env.example
└── README.md
```

## 9. 원본 요구사항 검증 영역 매핑
| 요구 | 본 설계에서의 대응 |
|------|-------------------|
| V1 정형 표 추출 | DI `tables` → 표 청크 → table-index |
| V2 다년도 통합 | `year`·`fund_name` 메타데이터 + 교차 조회 (추가 자료 적재 후) |
| V3 서술형 요약 | narrative 청크 + LLM 요약 응답 |
| V4 가로 페이지 추출 | DI bounding region + 표 청크 |
| V5 다중 문서 교차 참조 | `cross_reference` 도구 + Knowledge Agent |
| V6 RAG 종합 응답 품질 | Golden Q&A + Foundry Evaluation |
| V7 파이프라인 운영성 | CLI 재실행 + config 모델 교체 + 사용량 로깅 |
