# 파이프라인 & 검색 프로세스 상세 리뷰 리포트

> 대상: 수익자 홈페이지 AI 챗봇 PoC (MiraeAIAgentMVP)<br>
> 작성 목적: 문서 인식→적재→검색→에이전트 응답 전 과정의 동작 방식, 특히 **Azure Document Intelligence(DI)의 역할**과 **표 형태 값 추출** 방식을 상세히 조사·기록.<br>
> 코드 기준: `ingest/`, `search/`, `agent/`, `app/` (main 브랜치, P1~P12 + 추론 요약 스트리밍/2단계 접이식 UI 반영)

---

## 0. 전체 아키텍처 한눈에

```
                    ┌──────────────────────── 인제스트 (수동 재실행 CLI) ────────────────────────┐
 PDF (532p)         │  [1] DI 파싱     [2] 정규화      [3] 청킹        [4] 임베딩     [5] 적재      │
 (한글, 텍스트레이어) ─▶ prebuilt-layout ─▶ ParsedDoc ─▶ Chunk[817] ─▶ Foundry 3072d ─▶ AI Search   │
                    │  markdown+구조     문단/표/그림   (레이아웃인지)  (배치)         2개 인덱스   │
                    └──────────────────────────────────────────────────────────────────────────┘
                                                                                   │
                    ┌──────────────────────── 질의 처리 (실시간) ──────────────────▼───────────┐
 사용자 질문 ───────▶│  Agent(MAF)  ─▶ 도구: search_narrative/search_tables/make_*/show_source  │
                    │  질문분해→다중조회(하이브리드)→교차참조→인용→시각화→거부가드              │
                    │  추론요약·툴콜 스트림 파싱 → 2단계 접이식 UI + OTel→App Insights + 토큰 스트리밍 │
                    └──────────────────────────────────────────────────────────────────────────┘
```

- **필수 Azure 스택**: DI(파싱) · AI Search(검색+벡터) · Microsoft Foundry(LLM/임베딩/평가) · Microsoft Agent Framework(오케스트레이션). 전부 **키리스(Managed Identity/Entra RBAC)**.
- **현재 적재 규모**: 1개 문서(2025 자산운용부문) → **817 청크 = 서술 606 + 표 199 + 그림 12**.
- **추론(reasoning) 모델**: 채팅/추론 배포는 Foundry **`gpt-5.4-mini`**(배포명 `reasoning`, GlobalStandard). 진행 과정 노출을 위해 **reasoning summary**를 사용(`default_options`의 `reasoning.summary="auto"`, `effort="medium"`). 배포 용량은 스트리밍 추론 부하에 맞춰 **200K TPM**로 상향.

---

## 1. Azure Document Intelligence(DI)의 역할 — 문서 "인식"의 핵심

`ingest/parser.py` — `analyze_pdf()`

### 1.1 호출 방식
- 모델: **`prebuilt-layout`** (레이아웃 전용, OCR/구조 분석 통합)
- 출력 형식: **`DocumentContentFormat.MARKDOWN`** — 표를 마크다운 표로, 헤딩을 계층으로 변환
- 기능: `DocumentAnalysisFeature.KEY_VALUE_PAIRS`
- 입력: `AnalyzeDocumentRequest(bytes_source=<PDF 바이트>)`
- 인증: `DefaultAzureCredential`(키리스)

### 1.2 DI가 "인식"해서 주는 것 (왜 DI가 필수인가)
일반 PDF 텍스트 추출(pdftotext)은 **표가 뭉개지고**(행·열 붕괴), 헤딩/페이지번호/그림을 구분하지 못합니다. DI는 문서를 **구조적으로 인식**해 다음을 제공합니다. 우리 파이프라인은 이를 전부 활용합니다:

| DI 산출물 | 내용 | 파이프라인에서의 활용 |
|---|---|---|
| `content` (markdown) | 문서 전체 마크다운(표=MD 표) | 참조/보존 |
| `paragraphs[].role` | `title`/`sectionHeading`/`pageHeader`/`pageNumber`/`footnote` 등 | **헤딩 계층·페이지번호를 정규식 없이 정확 분리** |
| `paragraphs[].boundingRegions[].pageNumber` | 각 문단의 **물리 페이지** | 청크 `page_physical` |
| `paragraphs[].spans[].offset` | 문서 내 **문자 오프셋**(문서 순서) | 표·그림을 문단과 **문서 순서로 인터리브** (section_path 정확도의 핵심) |
| `tables[]` | `rowCount`/`columnCount`/`cells[]`(rowIndex·columnIndex·content) | **표를 셀 격자로 재구성** (아래 §3) |
| `figures[]` | `boundingRegions`(page+polygon)·`spans` | 그림 영역 크롭→멀티모달 설명(§6) |

> **핵심**: DI가 없으면 표의 행·열 구조와 헤딩 계층을 알 수 없습니다. DI의 `role`·`tables.cells`·`spans.offset`이 이 파이프라인 품질의 토대입니다.

### 1.3 캐시
DI 결과(`result.as_dict()`)를 `.ingest_cache/{doc_id}.json`에 저장. 최초 분석 ~50초, 이후 재사용 ~0.3초 → **청킹/임베딩을 반복 실험해도 DI 재호출·재과금 없음**.

---

## 2. 정규화 — ParsedDoc

`ingest/models.py`, `ingest/parser.py`

DI의 방대한 JSON을 SDK와 분리된 단순 모델로 변환(→ 청킹 로직을 **오프라인 유닛 테스트** 가능하게 함):

| 모델 | 필드 |
|---|---|
| `ParsedParagraph` | `role`, `content`, `page`, `offset` |
| `ParsedTable` | `markdown`, `page`, `caption`, `offset` |
| `ParsedFigure` | `page`, `polygon`, `offset`, `caption` |
| `ParsedDoc` | `doc_id`, `markdown`, `paragraphs[]`, `tables[]`, `figures[]` |

---

## 3. 표 형태 값의 추출 — "표를 잘 가져오는" 방식 (핵심 관심사)

### 3.1 DI 셀 → 마크다운 표 재구성
`ingest/parser.py` — `_table_to_markdown(table)`

1. `rowCount × columnCount` 크기의 빈 격자 생성
2. `table["cells"]`의 각 셀을 `(rowIndex, columnIndex)` 위치에 배치 → **행·열 정렬 보존**
3. 셀 정제: 줄바꿈 제거, **파이프(`|`) 이스케이프**(표 깨짐 방지)
4. 빈 표(0행/0열) 가드(IndexError 방지)
5. 첫 행을 헤더로, 이후 `|---|` 구분선 + 데이터 행 생성

```
| 구분 | 운용 수익률 | 기준 수익률 | 초과 수익률 | 목표 초과수익률 | 상대수익률 등급 |
|---|---|---|---|---|---|
| 5년  | 9.75% | 9.59% | 0.16% | 0.25% | 우수 |
| 20년 | 6.90% | 6.82% | 0.08% | 0.33% | 보통 |
```
*(실제 table-index 청크 예시: 국민연금기금 상대수익률, p.241)*

### 3.2 표는 "통째로 1청크" (분할 금지)
`ingest/chunker.py` — `chunk_document()`

- 각 `ParsedTable` → **정확히 1개 `chunk_type="table"` 청크** (캡션 있으면 앞에 붙임).
- 이유: 표를 문자수로 쪼개면 행·열 맥락과 수치가 붕괴 → **셀 정확도·수치 인용이 무너짐**. 통째 보존이 V1(정형 표)·V4(가로 페이지) 품질의 핵심.

### 3.3 표의 위치 정보(section_path) — 문서 순서 인터리브
- 표 청크의 `section_path`는 **문서 오프셋 기준**으로, 표가 등장한 위치까지의 헤딩 스택을 결합.
- 구현: 문단과 표를 `offset`으로 정렬해 하나의 스트림으로 처리(초기엔 표를 문서 끝 헤딩으로 잘못 귀속하던 버그를 P2에서 수정) → 실측 **199개 표에 132개 고유 section_path**(로고/장식 아닌 실제 표는 각 기금·섹션에 정확 귀속).
- 효과: "어느 기금의 어느 표인지"가 식별 가능 → 근거 인용(V5)·향후 정형화의 기반.

### 3.4 표 청크의 메타데이터
`doc_id`, `section_path`(예: `08. 국민연금기금 > 3.1 평가결과 총괄표`), `page_physical`, `page_printed`, `chunk_type="table"`, (`year`/`fund_name`은 다문서 확장 시 채움).

### 3.5 표 값 검색·활용
- 표 청크는 **`table-index`** 로 라우팅되어(§5) 서술 인덱스와 분리 → 수치 질의 시 표만 정밀 조회 가능.
- 에이전트의 `search_tables` 도구가 이 인덱스를 하이브리드 검색(§7).
- 답변 시 `make_table` 도구로 **정형 표(cl.Dataframe)** 로 렌더(§8).

> **표 추출의 한계(정직)**: DI 셀 재구성은 병합 셀(rowSpan/colSpan)의 상단-좌측만 채움. 셀 단위 100% 정확도(V1)의 **정량 대조 테스트는 아직 없음**(정답 표 부재). 정형 DB 적재는 범위 외(사용자 확정).

---

## 4. 서술 본문 청킹 — 레이아웃 인지 계층 청킹

`ingest/chunker.py`

- **헤딩 role**(`title`/`sectionHeading`)로 섹션 분리, 헤딩 스택으로 `section_path` 구성.
- 헤딩 깊이 추정: `1.`→1, `가.`→2, `ㅇ`/`-`→3.
- 긴 섹션은 문단 경계에서 슬라이딩 분할: **`max_chars=3600`(≈900토큰), 오버랩 `540`(15%)** → 경계 문맥 손실 방지.
- `pageNumber` role 문단에서 **인쇄 페이지번호**(`- 24 -`) 파싱 → `page_printed`(인쇄/PDF 오프셋 보정).
- 청크 id: `f"{doc_id}-{index}"` → 재실행 시 **upsert**(중복 없음).

---

## 5. 임베딩 & 적재 — 2개 하이브리드 인덱스

### 5.1 임베딩
`ingest/embedder.py` — Foundry **`text-embedding-3-large`, 3072차원**, 배치(32), 키리스 토큰 인증, 순서 보존.

### 5.2 인덱스 스키마 (동일 구조 2개)
`ingest/indexer.py` — `narrative-index`, `table-index`

| 필드 | 타입/속성 |
|---|---|
| `id` | key |
| `content` | searchable, **한글 분석기 `ko.lucene`** |
| `content_vector` | Collection(Single), **3072차원, HNSW** 프로필 `hnsw-profile` |
| `doc_id`,`chunk_type`,`section_path`,`fund_name` | filterable |
| `year`,`page_physical`,`page_printed` | Int32 filterable |
| 시맨틱 구성 | `sem` (title=section_path, content=content) |

### 5.3 라우팅 & upsert
`upload_chunks()` — `chunk_type=="table"` → `table-index`, 그 외(서술·**그림**) → `narrative-index`. 벡터 필수(없으면 예외). 재실행 시 동일 id upsert.

> **왜 2개 인덱스?** 서술(정성)과 표(정형/수치)를 분리해 유형별 최적 검색 + 에이전트가 **여러 인덱스를 목적별로 다중 조회**(agentic retrieval 기반).

---

## 6. 그림 이해 — 멀티모달 설명을 RAG 컨텍스트로

`ingest/figures.py`

- DI `figures`의 polygon으로 해당 페이지를 `pdftoppm`(150dpi) 렌더 후 **영역 크롭**(Pillow).
- **Foundry gpt-4o 멀티모달**(키리스)로 한국어 설명 생성 → `chunk_type="figure"` 청크(설명 텍스트)로 `narrative-index` 적재 → **그림 내용이 검색 가능**.
- 실측: 12개 figure 적재·검색 확인. (단, 본 보고서의 figure는 대부분 기관 로고/표지 장식이라 데이터 차트는 없음 — 파이프라인은 유형 무관 동작.)

---

## 7. 검색 프로세스 — 하이브리드 + Agentic Retrieval

### 7.1 하이브리드 검색 헬퍼
`search/hybrid.py` — `hybrid_search(index, query, top=5)`

한 번의 질의에서 **3가지 신호 결합**:
1. **BM25 키워드**(`search_text=query`)
2. **벡터 유사도**(질의를 3072d 임베딩 → `content_vector` 최근접, `VectorizedQuery`)
3. **시맨틱 재정렬**(`query_type="semantic"`, config `sem`)

반환: `SearchHit(id, content, section_path, page_physical, score, chunk_type)`.

### 7.2 Agentic Retrieval (에이전트 주도 다중 조회)
`agent/orchestrator.py` + `agent/tools.py`

- 에이전트(Foundry LLM, MAF)가 **질문을 하위 질의로 분해**하고, 목적별로 도구를 **여러 번** 호출:
  - `search_narrative(query)` → `narrative-index` 하이브리드
  - `search_tables(query)` → `table-index` 하이브리드
- 여러 인덱스·여러 질의 결과를 **교차 참조**해 답변 합성 → 이것이 스펙의 "Agentic Retrieval / 다중 문서 교차참조(V5)" 검증축. (관리형 AI Search Knowledge Base 대신 **에이전트 오케스트레이션으로 구현** — 제어·관측 우위, 안정 API.)
- 각 검색 결과는 `TraceRecorder`에 **출처(RetrievedSource)** 로 기록. 답변이 인용한 `[출처 N]`이 있으면 그 출처만 **"근거"** 카드로 표시하고, 모델이 인용 형식을 누락하면 이번 답변 생성에 검색된 자료를 (섹션·페이지 기준) 중복 제거해 **"참고한 자료"** 카드로 표시한다(`app/formatting.py` `cited_sources`·`dedup_sources`).

### 7.3 응답 합성 규칙 (시스템 프롬프트)
- **언어 규칙(최우선)**: 최종 답변뿐 아니라 사고 과정·추론 요약까지 **사용자 질문 언어**로 서술하도록 유도.
- 정성=narrative, 수치/등급/표=tables, 필요 시 다중 호출·교차 확인
- **`[출처 N]` 인용**(section_path+page)
- **근거 없으면 "제공된 자료에서 확인할 수 없습니다"로 거부**(할루시네이션 방어)
- 시각화 도구(표/차트/원문이미지)는 **검색으로 확인한 실제 값만** 사용

---

## 8. 응답 & UI — 시각화·스트리밍·2단계 접이식 진행 표시·관측

`agent/visuals.py`, `agent/translate.py`, `app/chat.py`, `app/visual_bind.py`, `app/formatting.py`

- **시각화 도구**(에이전트가 필요 시 호출): `make_table`→`cl.Dataframe`, `make_chart`→`cl.Plotly`(line/bar), `show_source_page(page)`→원문 페이지 렌더 `cl.Image`.
- **토큰 스트리밍**: `agent.run(stream=True)` → 답변이 토큰 단위로 흐름.
- **진행 과정 라이브 표시(스트림 콘텐츠 직접 파싱)**: 별도 미들웨어 없이, 스트림 업데이트의 `contents`를 유형별로 파싱해 **2단계 접이식**으로 노출.
  - **부모 "생각 중" 스텝**: 모델의 **추론 요약**(`text_reasoning`)을 도착 순서대로 누적. (`default_options`의 `reasoning.summary="auto"`로 활성화.)
  - **자식 도구 스텝**: 각 도구 호출(`function_call`)을 **`call_id`별 독립 자식 스텝**으로 열고(입력=검색어), 결과(`function_result`) 도착 시 해당 스텝의 출력(검색 결과 전문)을 채움. 병렬 호출·결과가 뒤섞여 도착해도 각자의 접이식 스텝에 정확히 담겨 **정렬이 엇갈리지 않음**.
- **추론 요약 언어 번역**(`agent/translate.py`): reasoning summary는 모델이 영어로 생성하는 경우가 많으므로, 질문 언어와 다르면 **세그먼트 단위로 번역**(Foundry gpt-4o 평가 배포 재사용)해 "생각 중"에 표시. 도구 입력/결과는 이미 질문 언어라 원문 그대로.
- **출처 카드**: 답변이 인용한 `[출처 N]`은 **"근거"**, 인용 누락 시 검색된 자료를 dedup해 **"참고한 자료"**로 표시(§7.2).
- **UI 언어**: `.chainlit/translations/ko-KR.json` + `config.toml`의 `language="ko-KR"`로 강제. 스텝 상태 라벨("Using/Used")을 비워 **"생각 중"** 등 스텝명만 노출.
- **자가 점검 루프(P12)**: 최대 2라운드. 1라운드 답변을 Foundry judge로 점검(`critique`)해 부족하면 보완 질의로 재조회(`augmented_question`), 점검 실패 시 안전하게 통과.
- **관측성**: OpenTelemetry로 에이전트 실행·툴 콜(근거/답변)을 **Azure Application Insights**에 기록(민감 데이터 포함).

---

## 9. 운영(재실행) 방법

```bash
# 신규 PDF 추가 시 동일 명령을 새 --doc-id로 재실행하면 upsert
uv run python -m ingest.run --pdf "Docs/<파일>.pdf" --doc-id "<고유ID>"
#  → DI(캐시) → 청킹 → 그림 설명 → 임베딩 → 2개 인덱스 적재
#  --no-figures 로 그림 설명 비활성, --no-cache 로 DI 재분석
```
- 완전 자동/노코드 파이프라인은 범위 외(사용자 확정) — **수동 재실행 CLI로 충분**.

---

## 10. 품질 지표(P5 평가, Foundry judge)

| 지표 | 결과 | 목표 |
|---|---|---|
| 정확도(groundedness 통과율) | 86.7% | 80% ✅ |
| 근거 인용율 | 100% | 90% ✅ |
| 할루시네이션 방어 | 100% | 90% ✅ |
| relevance / retrieval / coherence | 4.67 / 4.67 / 4.40 (1~5) | — |
| fluency | 2.27 | (인용 인라인으로 낮음 — 목표 지표 아님) |

---

## 11. 요약 & 남은 갭

**동작 요약**: DI가 한글 PDF의 **표·헤딩·그림·오프셋을 구조적으로 인식** → 표는 셀 격자로 재구성해 통째 청크(table-index), 서술은 계층 청킹(narrative-index), 그림은 멀티모달 설명으로 인덱싱 → 3072d 임베딩 → **BM25+벡터+시맨틱 하이브리드** → **에이전트가 질문 분해·다중 인덱스 조회·교차참조**로 근거 인용 답변, 시각화·스트리밍·관측 포함.

**남은 갭(문서 추가 시 해소)**:
- **V2 다년도/V5 진짜 다중문서**: 현재 1개 문서·1개 연도만 → 2024·평가근거 자료 추가 시 실증(+ `year`/`fund_name` 채움).
- **V1 셀 100% / V4 가로페이지 95%**: 정답 대조 정량 테스트 미구현(선택).
- **표 병합 셀** 완전 처리(rowSpan/colSpan) 개선 여지.
