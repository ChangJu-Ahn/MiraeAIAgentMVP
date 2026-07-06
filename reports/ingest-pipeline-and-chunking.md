# 문서 인식 · 청킹 · 처리 파이프라인 레포트

> 대상: 수익자 홈페이지 AI 챗봇 PoC (P2 인제스트)
> 구현 위치: `ingest/`, `search/`
> 문서: 2025회계연도 기금운용평가보고서 (532p, 한글 PDF)

## 1. 한눈에 보는 전체 흐름

```
PDF ──▶ [1.파싱]  ──▶ [2.정규화]  ──▶ [3.청킹]  ──▶ [4.임베딩]  ──▶ [5.적재]  ──▶ [6.검색]
      Azure DI      ParsedDoc     Chunk 목록     Foundry벡터    AI Search      하이브리드
      (마크다운)    (문단/표/역할)  (레이아웃인지)  (3072차원)     2개 인덱스     (벡터+BM25+시맨틱)
```

각 단계는 독립 모듈이며, DI 분석 결과는 로컬 캐시(`.ingest_cache/`)되어 청킹·임베딩을 반복 실험해도 DI를 재호출(재과금)하지 않습니다.

---

## 2. 단계별 상세

### 단계 1 — 문서 인식 (Azure Document Intelligence)
`ingest/parser.py`

- **모델**: `prebuilt-layout`, 출력 형식 `MARKDOWN`, 기능 `KEY_VALUE_PAIRS`.
- **키리스 인증**: `DefaultAzureCredential` (API 키 미사용).
- DI가 반환하는 구조에서 다음을 활용합니다:
  - `content` → 문서 전체 **마크다운** (표는 마크다운 표로 보존)
  - `paragraphs[].role` → **title / sectionHeading / pageHeader / pageNumber** 등 (헤딩 계층·페이지번호를 정규식이 아닌 DI 구조로 인식)
  - `paragraphs[].boundingRegions[].pageNumber` → 각 문단의 **물리 페이지**
  - `tables[]` → 셀(rowIndex/columnIndex)로부터 **표를 재구성**
- **캐시**: 원본 결과(`as_dict()`)를 `.ingest_cache/{doc_id}.json`에 저장 후 재사용 (최초 ~50초, 재사용 ~0.3초).

### 단계 2 — 정규화 (ParsedDoc)
`ingest/models.py`, `ingest/parser.py`

DI의 방대한 JSON을 처리하기 쉬운 단순 모델로 변환합니다. 이 정규화 덕분에 청킹 로직은 SDK와 분리되어 **오프라인 단위 테스트**가 가능합니다.

| 모델 | 내용 |
|------|------|
| `ParsedParagraph` | `role`, `content`, `page` |
| `ParsedTable` | `markdown`, `page`, `caption` |
| `ParsedDoc` | `doc_id`, 전체 `markdown`, `paragraphs[]`, `tables[]` |

표 재구성 시: 줄바꿈 제거 + **파이프(`|`) 이스케이프**(표 깨짐 방지), 빈 표 가드(오류 방지) 처리.

### 단계 3 — 청킹 전략 ⭐ (핵심)
`ingest/chunker.py` — `chunk_document(doc, max_chars=3600, overlap_chars=540)`

**전략명: 레이아웃 인지 계층 청킹 (Layout-aware Hierarchical Chunking)**

핵심 규칙 5가지:

1. **표는 통째로 1개 청크** (분할 금지)
   - 각 `ParsedTable` → `chunk_type="table"` 청크 1개. 캡션을 앞에 붙여 함께 보존.
   - 이유: 표를 쪼개면 행·열 맥락과 수치가 손상됨 → V1(정형 표)/V4(가로 페이지) 정확도 보호.

2. **헤딩 기준 섹션 분리 + `section_path` 구성**
   - `title`/`sectionHeading` role을 만나면 헤딩 스택 갱신.
   - 헤딩 깊이 추정: `1.`→깊이1, `가.`→깊이2, `ㅇ`/`-`→깊이3.
   - 각 청크에 계층 경로 부여, 예: `Ⅱ. 자산운용부문 평가결과 > 1. 평가 개요 > 가. 평가의 특징`.
   - 이유: 교차참조(V5)·다년도(V2) 시 정밀 필터·근거 인용에 사용.

3. **긴 섹션은 문단 경계에서 슬라이딩 분할 (오버랩 포함)**
   - 목표 크기 `max_chars≈3600`(≈900토큰), **오버랩 `540`(15%)**.
   - 연속 청크가 15% 겹쳐 문맥이 경계에서 끊기지 않도록 함.

4. **페이지 매핑**
   - `page_physical`: DI가 준 물리 페이지.
   - `page_printed`: 같은 페이지의 `role=="pageNumber"` 문단(예: `- 24 -`)에서 인쇄 페이지번호를 파싱해 채움 (인쇄/PDF 페이지 오프셋 보정).

5. **안정적 ID**
   - `id = f"{doc_id}-{순번}"` → 재실행 시 동일 문서는 **upsert**(덮어쓰기)되어 중복 없음.

각 청크의 메타데이터: `doc_id`, `section_path`, `page_physical`, `page_printed`, `chunk_type`(narrative|table), `year`, `fund_name`.

### 단계 4 — 임베딩 (Microsoft Foundry)
`ingest/embedder.py` — `embed_texts(texts, batch_size=32)`

- 모델 `text-embedding-3-large`, **차원 3072**.
- 배치(기본 32개)로 호출하여 순서 보존, 키리스 토큰 인증.

### 단계 5 — 적재 (Azure AI Search, 2개 인덱스)
`ingest/indexer.py`

- **`narrative-index`**: 서술 본문 청크
- **`table-index`**: 표 청크
- `chunk_type`에 따라 자동 라우팅하여 `upload_documents`로 **upsert**.
- 인덱스 스키마(둘 다 동일):
  - `content`(검색 가능, **한글 분석기 `ko.lucene`**)
  - `content_vector`(3072차원, **HNSW** 벡터 인덱스)
  - 필터 필드: `doc_id`, `chunk_type`, `section_path`, `fund_name`, `year`, `page_physical`, `page_printed`
  - **시맨틱 구성 `sem`** (제목=section_path, 본문=content)

### 단계 6 — 검색 (하이브리드)
`search/hybrid.py` — `hybrid_search(index_name, query, top=5)`

- 한 번의 질의에서 **세 가지를 결합**:
  1. **BM25 키워드** 검색 (`search_text`)
  2. **벡터 유사도** 검색 (질의를 임베딩 → `content_vector` 최근접)
  3. **시맨틱 재정렬** (`query_type="semantic"`, config `sem`)
- 반환: `SearchHit`(id, content, section_path, page_physical, score, chunk_type).

---

## 3. 왜 이렇게 설계했나 (근거)

| 결정 | 이유 | 관련 검증항목 |
|------|------|--------------|
| 표를 분할하지 않음 | 수치·행열 맥락 보존 | V1, V4 |
| 헤딩 계층 `section_path` | 근거 위치 인용·교차참조 | V3, V5 |
| 15% 오버랩 | 경계 문맥 손실 방지 | V6 |
| narrative/table **2개 인덱스** | 유형별 최적 검색 + 다중 인덱스 조회 기반 | V5, agentic retrieval |
| 한글 분석기 + 벡터 + 시맨틱 | 한글 하이브리드 품질 | V6 |
| DI 결과 캐시 + upsert CLI | 재실행 운영 편의 | V7 |

---

## 4. 재실행 방법 (운영자)

```bash
# 새 문서 추가 시 동일 명령을 새 --doc-id로 재실행하면 upsert
uv run python -m ingest.run --pdf "Docs/<파일>.pdf" --doc-id "<고유ID>"
```

- 이미 적재한 문서를 같은 `doc_id`로 재실행하면 청크가 덮어써져 중복이 없습니다.
- `--pages "1-100"`으로 페이지 범위 지정, `--no-cache`로 DI 재분석 가능.

---

## 5. 현재 상태 & 다음 단계

- **완료(P2)**: 파싱·정규화·청킹·임베딩·2개 하이브리드 인덱스 적재·하이브리드 검색 헬퍼. (일부 태스크는 리뷰 진행 중)
- **다음(P3)**: Microsoft Agent Framework 에이전트가 이 검색 헬퍼로 **여러 인덱스를 다중 조회·교차참조**(= agentic retrieval 검증)하고 근거를 인용해 답변. Chainlit UI(P4), Foundry Evaluation(P5)로 이어집니다.

> 요약: **DI로 한글 문서의 레이아웃·표·헤딩을 구조적으로 인식 → 표는 통째로, 본문은 섹션 계층+오버랩으로 청킹 → 3072차원 임베딩 → 유형별 2개 인덱스에 적재 → 벡터+키워드+시맨틱 하이브리드로 검색.**
