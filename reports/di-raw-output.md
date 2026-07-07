# Document Intelligence 원본 출력 분석 리포트

> 대상: 수익자 홈페이지 AI 챗봇 PoC (MiraeAIAgentMVP)
> 원본 PDF: `Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf` (532p, 한글, 텍스트 레이어 있음)
> DI 모델: **`prebuilt-layout`** (api-version `2024-11-30`), 출력 형식 **MARKDOWN**, 기능 KEY_VALUE_PAIRS
> 원본 캐시: `.ingest_cache/gicheum-2025-asset.json` (**67MB**, git 제외됨)
> **마크다운 전문**: [`reports/di-raw-markdown-full.md`](./di-raw-markdown-full.md) (DI `content` 전체, ~1.35MB)
> 코드 기준: `ingest/parser.py`, `ingest/chunker.py`

---

## 1. 한눈에 — DI가 원본 PDF에서 만들어낸 것

Azure Document Intelligence에 532페이지 PDF를 태운 결과(1회 분석):

| 항목 | 값 | 설명 |
|---|---|---|
| `content` (마크다운) | **731,412자** | 문서 전체를 하나의 마크다운 문자열로 재구성 |
| `pages` | **532** | 페이지별 단어·라인·스팬 좌표 |
| `paragraphs` | **18,963** | 역할(role) 태깅된 문단 단위 |
| `tables` | **199** | 셀 단위 구조화된 표 |
| `figures` | **12** | 그림/차트 영역(폴리곤 좌표) |
| `sections` | **688** | 논리적 섹션 계층 |
| 원본 JSON 크기 | **67MB** | 위 모든 요소 + 좌표/스팬 포함 |

> 핵심: DI는 단순 텍스트 추출이 아니라 **레이아웃을 인지한 구조화 출력**을 만든다. 이 구조(문단 역할·표 셀·페이지 마커)가 뒤 단계의 청킹 품질을 좌우한다.

---

## 2. 출력 형태 — 마크다운(`content`) 구조

DI는 문서를 마크다운으로 재구성하되, 레이아웃 정보를 **HTML 태그와 주석**으로 함께 표현한다. 실제 서두(목차) 발췌:

```markdown
<!-- PageHeader="www.mpb.go.kr" -->

# 2025 회계연도 기금운용 평가보고서

<figure>
Ⅱ
</figure>

자산운용부문
2026\. 5\.

<!-- PageBreak -->

## 목 차

## Ⅰ . 2025회계연도 기금운용평가 자산운용부문 개요 1
1\. 평가의 목적
1
...
```

**등장하는 마커:**
| 마커 | 의미 | 파이프라인에서의 활용 |
|---|---|---|
| `# / ## / ###` | 제목·섹션 헤딩 | 섹션 경로(section_path) 구성 |
| `<!-- PageBreak -->` | 페이지 경계 | 물리 페이지 추적 |
| `<!-- PageNumber="- i -" -->` | 인쇄 페이지 번호 | printed page ↔ physical page 매핑 |
| `<!-- PageHeader="..." -->` | 머리말 | 노이즈로 제외 |
| `<figure>...</figure>` | 그림/로고 영역 | 그림 청크 처리 |
| `<table>...</table>` | 표 | 표 청크(별도 인덱스) |

---

## 3. 문단 역할(role) 분포

DI가 18,963개 문단에 부여한 역할:

| role | 개수 | 파이프라인 처리 (`ingest/chunker.py`) |
|---|---|---|
| `body` | 17,773 | 본문 → 서술형 청크로 누적 |
| `sectionHeading` | 642 | 헤딩 스택 갱신 → section_path |
| `pageNumber` | 502 | 인쇄 페이지 번호 매핑용, 청크에서 제외 |
| `title` | 45 | 최상위 제목 → 헤딩 스택 리셋 |
| `pageHeader` | 1 | 머리말, 제외 |

> `chunk_document`는 `title`/`sectionHeading`으로 섹션 경로를 만들고, `pageNumber`는 인쇄 페이지 매핑에만 쓰고 본문에서 뺀다.

---

## 4. 표(table) 표현 방식

표는 `content` 안에서 **`<table>` HTML**로, `caption`이 있으면 함께 나온다. 실제 예시(대규모 기금 평가의 등급 환산표):

```html
<table>
<caption>< 9단계 평가등급별 평점 ></caption>
<tr><td>등급</td><td>1</td><td>2</td>...<td>9</td></tr>
<tr><td>Z값</td><td>~- 2.1</td><td>-2.1~ -1.5</td>...<td>2.1~</td></tr>
<tr><td>평점</td><td>0.0</td><td>12.5</td>...<td>100.0</td></tr>
</table>
```

동시에 `tables[]` 배열에는 **셀 단위 구조**도 담긴다(좌표·스팬 포함). 예: 평가단 구성표는 `rowCount=19, columnCount=4, cells=59`, 첫 행 헤더 = `['구분', '성명 (출생)', '소속 및 직위', '학력 및 주요경력']`.

> 파이프라인은 표를 **별도 인덱스(search_tables)** 로 적재해, 수치·등급 질의가 표에 정확히 매칭되도록 한다.

---

## 5. 그림(figure) 표현

12개 `figures`는 각각 `boundingRegions`(페이지+폴리곤 좌표), `spans`, `elements`를 가진다. 대부분 표지 로고·차트 영역이며 caption은 대체로 없다(예: figure[0] = page 1, caption `None`).

> 그림은 `show_source_page`로 **원문 페이지 이미지**를 렌더링해 보여줄 때 활용된다(사용자가 원문 요청 시).

---

## 6. 원본 데이터 접근 · 재생성 방법

| 무엇 | 위치 | 비고 |
|---|---|---|
| **마크다운 전문** | [`reports/di-raw-markdown-full.md`](./di-raw-markdown-full.md) | 사람이 읽는 형태의 DI 출력 전체(~1.35MB) |
| 원본 JSON 전체 | `.ingest_cache/gicheum-2025-asset.json` (67MB) | git 제외(`.gitignore`), 로컬에만 존재 |
| 재생성 | `ingest/parser.py`의 `analyze_pdf(..., use_cache=False)` | DI 재호출(재과금). 기본은 캐시 사용 |

**동작 원리**: `analyze_pdf`는 `.ingest_cache/{doc_id}.json`이 있으면 DI를 재호출하지 않고 캐시를 파싱한다(`ingest/parser.py:82-88`). 신규 PDF는 이 캐시가 없으므로 DI를 1회 호출 후 저장한다 — 즉 **수동 재실행형** 인제스트.

---

## 7. 이 출력이 파이프라인으로 이어지는 흐름

```
DI content/paragraphs/tables/figures
        │  ingest/parser.py: _result_to_parsed → ParsedDoc(문단/표/그림, offset)
        ▼
ingest/chunker.py: 문단·표를 offset 순 병합 → 레이아웃 인지 청킹
        │   · title/sectionHeading으로 section_path
        │   · pageNumber로 인쇄↔물리 페이지 매핑
        │   · 표는 <table> 그대로 → 표 청크
        ▼
Chunk[] → 임베딩 → AI Search 2개 인덱스(narrative / tables)
```

자세한 청킹·검색 과정은 [`ingest-pipeline-and-chunking.md`](./ingest-pipeline-and-chunking.md), [`pipeline-and-search-process.md`](./pipeline-and-search-process.md) 참조.

---

## 8. 한 줄 요약

DI(`prebuilt-layout`)는 532p PDF를 **731,412자 마크다운 + 18,963 문단 + 199 표 + 12 그림 + 532 페이지** 의 레이아웃 인지 구조로 변환했다. 마크다운 전문은 [`reports/di-raw-markdown-full.md`](./di-raw-markdown-full.md)에서 그대로 확인할 수 있고, 이 구조가 청킹·검색 품질의 출발점이 된다.
