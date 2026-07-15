# 평가 리포트 (Foundry Evaluation)

- 총 문항: 16

## 평가 메타데이터
| 항목 | 값 |
|---|---|
| 데이터셋 제목 | Chatbot_질문지리스트_20260713 |
| workbook 파일 | Docs/Chatbot_질문지리스트_20260713.xlsx |
| sheet | Sheet1 |
| 문항 수 | 16 |
| 평가 시각 | 2026-07-15T00:17:17.124210+00:00 |
| judge deployment | chat |
| source snippet 제한 | Stored source snippets are truncated to 300 chars. |

## 목표선 대비
| 지표 | 결과 | 목표 | 판정 |
|---|---|---|---|
| 정확도(groundedness 통과율) | 100.0% | 80% | PASS |
| 근거 인용율 | 100.0% | 90% | PASS |
| 할루시네이션 방어(원문부재 거부율) | N/A | 90% | N/A |

## 지표별 평균 점수 (1~5, Foundry judge)
| 지표 | 평균 | 통과율 | 통과 기준 |
|---|---|---|---|
| groundedness | 5.00 | 100.0% | 3.0 |
| relevance | 4.69 | 100.0% | 3.0 |
| similarity | 3.88 | 87.5% | 3.0 |
| coherence | 4.75 | 100.0% | 3.0 |
| fluency | 5.00 | 100.0% | 3.0 |

## 유형별 결과
| 유형 | 문항수 | groundedness 통과 | 인용율 |
|---|---|---|---|
| 미분류 | 16 | 100% | 100% |

## 문항별 결과
| ID | 유형 | groundedness | relevance | similarity | coherence | fluency |
|---|---|---|---|---|---|---|
| 1 | 미분류 | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 2 | 미분류 | 5.00 / PASS | 5.00 / PASS | 4.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 3 | 미분류 | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 4 | 미분류 | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS | 4.00 / PASS | 5.00 / PASS |
| 5 | 미분류 | 5.00 / PASS | 4.00 / PASS | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 6 | 미분류 | 5.00 / PASS | 4.00 / PASS | 2.00 / FAIL | 4.00 / PASS | 5.00 / PASS |
| 7 | 미분류 | 5.00 / PASS | 5.00 / PASS | 4.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 8 | 미분류 | 5.00 / PASS | 4.00 / PASS | 1.00 / FAIL | 4.00 / PASS | 5.00 / PASS |
| 9 | 미분류 | 5.00 / PASS | 4.00 / PASS | 4.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 10 | 미분류 | 5.00 / PASS | 5.00 / PASS | 4.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 11 | 미분류 | 5.00 / PASS | 5.00 / PASS | 3.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 12 | 미분류 | 5.00 / PASS | 5.00 / PASS | 3.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 13 | 미분류 | 5.00 / PASS | 5.00 / PASS | 4.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 14 | 미분류 | 5.00 / PASS | 5.00 / PASS | 4.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 15 | 미분류 | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS | 5.00 / PASS |
| 16 | 미분류 | 5.00 / PASS | 4.00 / PASS | 4.00 / PASS | 4.00 / PASS | 5.00 / PASS |

## 실패 군집
| 우선순위 | 코드 | 제목 | 문항 ID | 근거 | 권고 |
|---|---|---|---|---|---|
| 3 | ground-truth-key-points | 검토 정답 핵심 포인트 누락 후보 | 6, 8 | 6: failed similarity<br>8: failed similarity | 답변과 검토 정답을 대조해 누락된 핵심 포인트를 검색 및 합성 단계에 반영합니다. |

## 실패 문항 상세
### 6
- 유형: 미분류
- 실패 지표: similarity

#### 질문
```text
공무원연금기금의 2023~2025회계연도 최종등급 추이는?
```

#### 검토 정답 (ground_truth)
```text
2023 우수 · 2024 우수 · 2025 우수 (3년 연속 우수 유지)
```

#### 실제 답변
```text
공무원연금기금의 2023~2025회계연도 **최종등급 추이**는, 제공된 자료 기준으로는 **2025년만 확인 가능**하고 2023년·2024년은 **제공된 자료에서 확인할 수 없습니다**. 2025년 최종등급은 **우수**입니다. [출처 1][출처 2][출처 3]

- 2023년: 제공된 자료에서 확인할 수 없음 [출처 1]
- 2024년: 제공된 자료에서 확인할 수 없음 [출처 2]
- 2025년: 우수 [출처 3]

따라서 **2023~2025 전 기간의 실제 추이 비교는 제공된 자료만으로는 불가능**합니다.
```

#### Judge context (exact)
```text
기금명: 공무원연금기금
fund_id: 공무원연금기금
연도: 2025
소관부처: 인사혁신처
별칭: 없음

[출처 1] corpus manifest 확인 결과, 2023회계연도 기금운용평가보고서는 제공된 corpus에 없습니다. 해당 연도의 값을 다른 연도 문서에서 추론하거나 대체하지 말고, 제공된 자료에서 확인할 수 없다고 답하세요.

[출처 2] corpus manifest 확인 결과, 2024회계연도 기금운용평가보고서는 제공된 corpus에 없습니다. 해당 연도의 값을 다른 연도 문서에서 추론하거나 대체하지 말고, 제공된 자료에서 확인할 수 없다고 답하세요.

## 공무원연금기금 — 2025년 평가 결과
- 종합등급: 최종등급 우수 [출처 3]

제공된 corpus에 2023회계연도 기금운용평가보고서는 없습니다. 제공된 report 연도: 2021, 2022, 2025.

제공된 corpus에 2024회계연도 기금운용평가보고서는 없습니다. 제공된 report 연도: 2021, 2022, 2025.

|  | 우수 | 공무원연금기금, 산업재해보상보험및예방기금 |
```

#### Judge 판정 이유
| 지표 | 점수 | 판정 | 이유 |
|---|---|---|---|
| groundedness | 5.00 | PASS | Let's think step by step: The QUERY asks for the 최종등급 추이 (final grade trend) of the 공무원연금기금 for the years 2023–2025. The CONTEXT explicitly states that the reports for 2023 and 2024 are not available and should not be inferred or substituted, while the 2025 report indicates a 최종등급 of 우수. The RESPONSE correctly states that the 2023 and 2024 grades cannot be confirmed due to lack of data and accurately provides the 2025 grade as 우수, citing the appropriate sources. Furthermore, the RESPONSE explicitly mentions that a full trend comparison is not possible due to the absence of data for 2023 and 2024, which aligns with the CONTEXT. The RESPONSE is fully grounded in the CONTEXT, accurate, complete, and does not introduce any extraneous or incorrect information. |
| relevance | 4.00 | PASS | The response directly addresses the user's query about the 2023-2025 최종등급 추이 for 공무원연금기금. It provides specific details for 2025 and clarifies the lack of data for 2023 and 2024, making it a complete and sufficient answer. |
| similarity | 2.00 | FAIL | The predicted answer does not provide a complete equivalence to the correct answer. While it mentions the 2025 rating as '우수', it fails to confirm the ratings for 2023 and 2024, which are explicitly stated as '우수' in the correct answer. The predicted answer also introduces additional information about the unavailability of data for 2023 and 2024, which deviates from the correct answer. |
| coherence | 4.00 | PASS | Let's think step by step: The RESPONSE directly addresses the QUERY about the final ratings trend of the 공무원연금기금 for the 2023-2025 fiscal years. It clearly states that data for 2023 and 2024 is unavailable and provides the 2025 rating as '우수' (excellent). The RESPONSE is logically structured, with a summary at the beginning and a breakdown of each year's data, including references to sources. The conclusion reiterates the limitations of the data, making the RESPONSE easy to follow and understand. The ideas are presented in a logical sequence, and the use of bold text emphasizes key points, enhancing clarity. Therefore, the RESPONSE is coherent and effectively addresses the QUERY. |
| fluency | 5.00 | PASS | The RESPONSE is written in Korean and demonstrates a high level of fluency. Grammar and syntax are correct throughout, with no noticeable errors. Vocabulary is appropriate and precise, and the sentence construction is clear and professional. The use of bold text for emphasis and the structured bullet points enhance readability and organization. The tone is formal and suitable for the context, and the overall naturalness and idiomatic usage are excellent. There are no language defects or awkward phrasings. |

#### 검색 trace
| tool | query | filter | n_hits |
|---|---|---|---|
| resolve_fund | name=공무원연금기금, year=2025 | N/A | 1 |
| get_fund_evaluations | fund_name=공무원연금기금, year=2023, metric=overall_grade | N/A | 0 |
| get_fund_evaluations | fund_name=공무원연금기금, year=2024, metric=overall_grade | N/A | 0 |
| get_fund_evaluations | fund_name=공무원연금기금, year=2025, metric=overall_grade | N/A | 1 |

#### 출처
| 번호 | index | path | page | snippet |
|---|---|---|---|---|
| 1 | corpus-manifest | 제공 문서 목록 | 0 | 제공된 corpus에 2023회계연도 기금운용평가보고서는 없습니다. 제공된 report 연도: 2021, 2022, 2025. |
| 2 | corpus-manifest | 제공 문서 목록 | 0 | 제공된 corpus에 2024회계연도 기금운용평가보고서는 없습니다. 제공된 report 연도: 2021, 2022, 2025. |
| 3 | evaluation-facts-index | Ⅱ. 2025회계연도 자산운용부문 평가결과 종합 > < 개선권고 주요 내용 > | 41 | \|  \| 우수 \| 공무원연금기금, 산업재해보상보험및예방기금 \| |

### 8
- 유형: 미분류
- 실패 지표: similarity

#### 질문
```text
2026회계연도 기금운용평가지침에서 계량(자산운용 성과) 평가는 어떤 지표 범주로 구성되는가?
```

#### 검토 정답 (ground_truth)
```text
(2026 평가지침 근거) ① 단기자산의 수익률 ② 중장기자산의 수익률 ③ 위험 대비 성과 ④ 운용상품 집중도 ⑤ 공공성 확보 노력도
```

#### 실제 답변
```text
제공된 자료에서는 **2026회계연도 기금운용평가지침**이 확인되지 않아, 계량(자산운용 성과) 평가가 어떤 **지표 범주**로 구성되는지 답할 수 없습니다.
즉, **2026년 지침의 해당 내용은 제공된 자료에서 확인할 수 없습니다**. [출처 1]
```

#### Judge context (exact)
```text
제공된 corpus에 2026회계연도 기금운용평가지침는 없습니다. 제공된 guideline 연도: 2021, 2022.
```

#### Judge 판정 이유
| 지표 | 점수 | 판정 | 이유 |
|---|---|---|---|
| groundedness | 5.00 | PASS | Let's think step by step: The CONTEXT explicitly states that the guidelines for the 2026 fiscal year are not provided, and only the guidelines for 2021 and 2022 are available. The QUERY asks about the evaluation criteria for asset management performance in the 2026 fiscal year guidelines. The RESPONSE correctly states that the information for the 2026 fiscal year guidelines is not available in the provided data and accurately concludes that it cannot answer the question based on the given CONTEXT. The RESPONSE is fully grounded in the CONTEXT, as it does not introduce any unrelated or incorrect information and directly addresses the QUERY with complete accuracy. |
| relevance | 4.00 | PASS | The response directly addresses the user's query by acknowledging the lack of available information on the 2026 guidelines. While it is accurate, it does not provide any additional context or insights, making it sufficient but not comprehensive. |
| similarity | 1.00 | FAIL | The predicted answer does not provide any equivalent information to the correct answer and instead states that the information is unavailable. |
| coherence | 4.00 | PASS | Let's think step by step: The QUERY asks about the specific indicators or categories that make up the quantitative (asset management performance) evaluation in the 2026 fiscal year fund management evaluation guidelines. The RESPONSE clearly states that the information about the 2026 guidelines is not available in the provided data, and therefore, it cannot answer the question. While the RESPONSE does not provide the requested information, it is logically structured, directly addresses the QUERY, and explains why the answer cannot be provided. The ideas are presented in a clear and orderly manner, making the RESPONSE coherent. However, since it does not provide any substantive information about the QUERY, it does not demonstrate the highest level of coherence. Thus, it aligns with the definition of a score of 4. |
| fluency | 5.00 | PASS | The response is written in Korean and demonstrates a high level of fluency. Grammar and syntax are correct, and the vocabulary is appropriate for the context. The sentence construction is clear and professional, with no noticeable errors or awkward phrasing. The use of emphasis through asterisks (e.g., **2026회계연도 기금운용평가지침**) is effective and enhances readability. Overall, the text is natural, precise, and idiomatic, suitable for professional or formal communication. |

#### 검색 trace
| tool | query | filter | n_hits |
|---|---|---|---|
| search_narrative | 계량 자산운용 성과 평가 지표 범주 구성 | year eq 2026 and doc_type eq 'guideline' | 0 |
| search_tables | 자산운용 성과 지표 범주 | year eq 2026 and doc_type eq 'guideline' | 0 |

#### 출처
| 번호 | index | path | page | snippet |
|---|---|---|---|---|
| 1 | corpus-manifest | 제공 문서 목록 | 0 | 제공된 corpus에 2026회계연도 기금운용평가지침는 없습니다. 제공된 guideline 연도: 2021, 2022. |

## 에이전트 시스템 개선 제안
1. 1순위 - 평가 데이터/trace 가시성: 6, 8의 ground_truth, exact judge context, judge reason, 검색 trace와 source를 같은 artifact에 보존합니다.
2. 2순위 - global-scope 분류와 coverage guard: 관찰 ID 없음를 우선 점검합니다. 전체 top-k를 일괄 확대하지 않고, 일반 사실 질문은 top-5를 유지하며 cross-section 비교는 TOC/metadata fan-out, 전역 집계와 순위는 정규화 레코드와 numeric aggregation tool로 처리합니다.
3. 3순위 - 정규화 및 집계 경로: fund_name/year/metric/score/max_score/grade/page/source_chunk 필드, sortable index, numeric aggregation tool을 ingest 및 retrieval 경로에 설계합니다.
4. 4순위 - 동일 데이터 재평가: 1, 10, 11, 12, 13, 14, 15, 16, 2, 3, 4, 5, 6, 7, 8, 9를 포함한 같은 workbook으로 변경 전후를 재평가합니다.
