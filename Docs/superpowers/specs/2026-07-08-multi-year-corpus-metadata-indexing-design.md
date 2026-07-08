# 멀티-연도/멀티-유형 코퍼스 — 메타데이터 필터 인덱싱 설계

- 작성일: 2026-07-08
- 대상: 수익자 홈페이지 AI 챗봇 PoC (MiraeAIAgentMVP)
- 상태: 승인됨 (브레인스토밍 완료, 구현 대기)

## 1. 배경 & 목적

기존에는 **2025 기금운용평가보고서(자산운용부문)** 1개만 `narrative-index`/`table-index` 2개 인덱스에 적재했다. 사용자가 문서 4개를 추가해 코퍼스가 확장된다:

- **보고서(report)**: 2025(적재됨), 2022, 2021 — 자산운용부문, 동일 구조
- **지침(guideline)**: 2021, 2022 — 대형중소형 평가지침

앞으로도 **연도별 동일 구조 문서가 계속 유입**된다. 목표: 하나의 챗봇이 확장된 코퍼스를 **메타데이터 필터**로 검색하고(연도·문서유형·기금명·기금규모), 연도 간 비교를 질의 시점에 처리한다.

### 결정된 방향 (브레인스토밍)
- 검색 방식: **filter_by_metadata** — 기본은 통합 검색, 질문에 연도/유형 등이 있으면 필터링.
- 인덱스 토폴로지: **접근 A — 2개 인덱스 유지 + 메타데이터 필터 필드** (유형이 늘어도 인덱스는 2개 고정).
- 필터 축 4개: `year`, `doc_type`, `fund_name`, `fund_scale` (모두 채택).
- 연도 비교: **query-time** (에이전트가 연도별 필터 검색 후 비교). 사전 요약 파이프라인 없음.
- 연도 미지정 시: **현재 날짜를 프롬프트에 주입**해 최신 회계연도 기본 조회 + 상대 시간 해석.

## 2. 비목표 (Out of Scope)
- 연도별 특징을 **사전 요약**해 저장하는 별도 파이프라인 (query-time 비교로 충분).
- 자동(무인) 인제스트 파이프라인 — 수동 재실행 CLI로 충분.
- 지침을 위한 별도 인덱스 (접근 B/C 기각) — 지침도 동일 2개 인덱스에 doc_type으로 구분.
- 비용 통제, 정형 DB 적재.

## 3. 인덱스 스키마

`narrative-index`, `table-index` **2개 유지**. 각 문서에 아래 메타데이터 필드 추가:

| 필드 | 타입 | 속성 | 추출 단위 | 추출 방법 |
|---|---|---|---|---|
| `year` | Int32 | filterable, facetable | 문서 | 인제스트 CLI/레지스트리 인자 (확정) |
| `doc_type` | String | filterable, facetable | 문서 | CLI/레지스트리 (`report`/`guideline`) |
| `fund_name` | String | filterable, facetable | 청크 | 섹션 헤딩에서 파생, 없으면 null |
| `fund_scale` | String | filterable, facetable | 청크/문서 | 헤딩 키워드 또는 문서 기본값, 없으면 null |

- `year`/`doc_type`은 문서 단위로 100% 정확(인자 명시).
- `fund_name`/`fund_scale`은 **베스트에포트 파생 + null 허용**. exact 필터가 과도하게 좁힐 수 있어 보조 필터로 취급(시맨틱 쿼리가 커버). `fund_name`은 `section_path`에도 존재.
- 스키마 필드 추가라 **인덱스 재생성 필요** → `reset_indexes()` + 전체 재인제스트.

## 4. 메타데이터 추출

주입 흐름:
```
CLI/레지스트리 인자(year, doc_type, fund_scale 기본값) ─┐
                                                       ├─▶ chunk_document(doc, meta)
DI 파싱 → 섹션 헤딩 스택 ───────────────────────────────┘     ├─ 문서단위: 모든 청크에 year/doc_type 부여
                                                             └─ 청크단위: 헤딩 스택에서 fund_name/fund_scale 파생
```

파생 로직(chunker):
- `fund_name`: 헤딩 스택에서 `기금`/`계정`으로 끝나는 항목 추출 (예: "8. 국민연금기금" → "국민연금기금"). 없으면 null.
- `fund_scale`: ① 헤딩에 "대규모" 포함 → `대규모`; "대형"/"중소형" 포함 → `대형중소형`; ② 없으면 CLI 기본값(지침=문서 단위 대형중소형); ③ 그래도 없으면 null.

## 5. 인제스트 파이프라인 & 문서 레지스트리

신규 `ingest/corpus.py`에 문서 레지스트리:
```python
CORPUS = [
  Doc(pdf="Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf",   doc_id="report-2025",       year=2025, doc_type="report",    fund_scale=None),
  Doc(pdf="Docs/2022회계연도기금운용평가보고서Ⅱ(자산운용부문).pdf",    doc_id="report-2022",       year=2022, doc_type="report",    fund_scale=None),
  Doc(pdf="Docs/2021회계연도 기금운용평가보고서Ⅱ(자산운용부문).pdf",   doc_id="report-2021",       year=2021, doc_type="report",    fund_scale=None),
  Doc(pdf="Docs/2021회계연도 기금운용평가지침1(대형중소형).pdf",       doc_id="guideline-2021-dh", year=2021, doc_type="guideline", fund_scale="대형중소형"),
  Doc(pdf="Docs/2022회계연도 기금운용평가지침1(대형중소형부문).pdf",   doc_id="guideline-2022-dh", year=2022, doc_type="guideline", fund_scale="대형중소형"),
]
```
- `python -m ingest.run --all [--reset]` — 레지스트리 전체 인제스트 (최초 1회 `--reset`으로 스키마 반영).
- `python -m ingest.run --doc-id report-2022` — 개별 재실행 (신규 PDF는 레지스트리에 한 줄 추가 후 실행).
- DI 캐시는 doc_id별(`.ingest_cache/{doc_id}.json`)로 저장 → 재실행 시 재과금 없음.

## 6. 검색 / 에이전트 도구 (메타 필터)

검색 도구에 선택적 필터 인자 추가:
```python
def search_narrative(query: str, year: int|None=None, doc_type: str|None=None,
                     fund_name: str|None=None, fund_scale: str|None=None) -> str
def search_tables(query: str, year=None, doc_type=None, fund_name=None, fund_scale=None) -> str
```
- `_run_tool`이 채워진 값만 **OData 필터**로 조립 → `hybrid_search(..., odata_filter=...)`.
  - 예: `year eq 2022 and doc_type eq 'report' and fund_name eq '국민연금기금'`.
  - 문자열 값은 작은따옴표 이스케이프 처리.
- `search/hybrid.py` `hybrid_search`에 `odata_filter: str|None=None` 추가 → `SearchClient.search(filter=...)`.

시스템 프롬프트 규칙 추가(`agent/orchestrator.py`, 오늘 날짜 동적 주입):
> "오늘은 {today}이다. 질문에 연도·문서유형(보고서/지침)·기금명·기금규모가 명시되면 검색 도구의 해당 필터 인자를 채워라. 연도 미지정 시 현재 시점 기준 가장 최신 회계연도 보고서를 기본으로 조회하라. '작년/최근' 등 상대 표현은 오늘 기준으로 해석하라. 여러 연도를 비교하는 질문이면 연도별로 각각 검색하라. fund_name/fund_scale 필터가 0건이면 해당 필터를 빼고 재검색하라."

동작 예시:
| 질문 | 필터 |
|---|---|
| "국민연금 2022 등급은?" | year=2022, doc_type=report, fund_name=국민연금기금 |
| "평가지침상 대형기금 배점 기준?" | doc_type=guideline, fund_scale=대형중소형 |
| "2021 vs 2025 결과 비교" | 2회 검색: year=2021 / year=2025 |
| "탁월 등급의 의미?" | 필터 없음(전체) |
| "최근 평가 요약해줘" (연도 미지정) | 최신 연도(2025) 기본 |

## 7. 마이그레이션

1. 코드 반영(모델/인덱서/청커/레지스트리/도구/프롬프트).
2. `python -m ingest.run --all --reset` — 인덱스 재생성 + 5개 문서 전체 인제스트 (DI는 신규 4개만 호출, 2025 캐시 사용).
3. 앱에서 필터 검색·연도 비교 확인.

## 8. 테스트

- **단위**: fund_name/fund_scale 파생(헤딩 스택 케이스), OData 필터 조립(non-null 조합·작은따옴표 이스케이프), Chunk 메타 필드 기본값, 레지스트리 정합성(경로 존재·doc_id 유일).
- **통합(실제 Azure)**: 재인제스트 후 `year=2022`→2022 문서만, `doc_type=guideline`→지침만, facet 카운트가 연도/유형별로 맞는지, 교차연도 비교 질의 동작.
- **회귀**: 기존 전체 테스트(streaming/formatting/eval/chunker 등) 그대로 통과.

## 9. 리스크 & 완화

| 리스크 | 완화 |
|---|---|
| reset로 기존 인덱스 삭제 → 재인제스트 전 검색 불가(1회) | 마이그레이션을 한 번에 수행, 재인제스트 직후 확인 |
| fund_name/fund_scale 파생 불완전 | null 허용 + 보조 필터 취급, 시맨틱 쿼리로 커버, "0건이면 필터 제거 재검색" 프롬프트 |
| exact 필터가 과도하게 좁힘 | year/doc_type만 강한 필터, fund_* 는 보조 |
| DI 신규 호출 4건 과금 | MVP 방침상 허용, 캐시로 재실행 무과금 |

## 10. 변경 파일 요약

| 파일 | 변경 |
|---|---|
| `ingest/models.py` | `Chunk`에 `year/doc_type/fund_name/fund_scale` 추가 |
| `ingest/indexer.py` | `build_index` 4개 필드 추가, `_chunk_to_doc` non-null 적재, `reset_indexes()` 유지 |
| `ingest/chunker.py` | `chunk_document(doc, meta)` — 문서 메타 주입 + fund_name/fund_scale 파생 |
| `ingest/corpus.py` (신규) | 문서 레지스트리 |
| `ingest/run.py` | `--all`/`--reset`/개별 doc-id, 메타 전달 |
| `agent/tools.py` | 검색 도구 필터 인자 + OData 조립 |
| `search/hybrid.py` | `hybrid_search(odata_filter=...)` |
| `agent/orchestrator.py` | 오늘 날짜 주입 + 필터/최신연도 기본 규칙 |
