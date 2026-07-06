# 기금운용평가보고서 AI 어시스턴트

기금운용평가보고서(한글 PDF)를 기반으로 답하는 **Agentic RAG 챗봇** 데모입니다.
Microsoft Foundry(gpt-5.4-mini, 추론) + Azure AI Search + Azure Document Intelligence + Microsoft Agent Framework.

## 에이전트가 하는 일
질문을 하위 질의로 분해해 여러 인덱스를 조회하고(**agentic retrieval**), 답변 후 스스로 충분성을 점검해 부족하면 **보완 질의로 다시 조회**하며(reflection, 최대 2라운드), 근거를 인용해 답변합니다. 자료에 없으면 답변을 거부합니다(**할루시네이션 방어**). 추론(reasoning)·도구 실행 과정이 단계로 표시되고, 답변은 토큰 단위로 스트리밍됩니다.

## 사용 가능한 도구
| 도구 | 동작 |
|------|------|
| 🔎 search_narrative | 서술형 본문(평가 개요·총평·정성 설명)을 하이브리드(벡터+BM25+시맨틱) 검색 |
| 📊 search_tables | 표(등급·점수·수익률 등 수치/정형 데이터)를 하이브리드 검색 |
| 📋 make_table | 정형 데이터를 정렬 가능한 표로 표시 |
| 📈 make_chart | 추세/비교를 차트(line/bar)로 표시 |
| 🖼️ show_source_page | 근거가 된 원문 PDF 페이지를 이미지로 표시 |

## 화면 구성
- 🔧 도구 단계: 에이전트가 무엇을 검색했고 무엇을 얻었는지(입력=질의, 결과)
- 답변: 근거 `[출처 N]` 인용, 필요 시 표·차트·원문 이미지
- 근거: **답변이 실제 인용한 출처만** (섹션 경로·페이지)

## 예시 질문
- 자산운용 평가의 목적은 무엇인가요?
- 탁월 등급과 우수 등급의 차이는?
- 국민연금기금의 상대수익률을 표로 보여줘
- (원문 확인) 국민연금 상대수익률 표의 원문 페이지를 보여줘

## 기반 서비스 (Azure AI 검증)
- **Document Intelligence** — 한글 PDF의 표·헤딩·그림을 구조적으로 인식(레이아웃→마크다운)
- **AI Search** — 2개 하이브리드 인덱스(서술/표), 벡터(3072d)+BM25+시맨틱
- **Foundry** — gpt-5.4-mini(추론) 답변, text-embedding-3-large 임베딩, gpt-4o 그림 설명, 답변 평가
- **Agent Framework** — 오케스트레이션, 미들웨어 트레이스
- **Application Insights** — OpenTelemetry 트레이스(도구 호출·추론 단계 관측)
