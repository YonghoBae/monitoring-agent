# 벡터 검색 개선 실험 — 최종 평가 진행 중

이 커밋은 **최종 시험 점수가 나오기 전의 선택 기록**이다. 최종 성능이나 우위를 주장하는 결과 보고서가 아니다. 완료 후 실제 최종 수치, 불확실성, 실행 비용과 한계를 추가한다.

개발용 공개 질문 문서 5,000개에서 세 다국어 임베딩과 두 리랭커, 입력 prefix·앞뒤 문서 조각·후보 수·BM25 후보 혼합을 포함한 13개 조건을 비교했다. 고정한 기준(최근 영어 nDCG@10 50% + 기존 한국어 번역 대조군 nDCG@10 50%)으로 **Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B, dense top50**을 선택했다. 개발 선택 점수는 0.715164다. 이 숫자는 최종 정확도가 아니다.

선택은 [final-selection-lock.json](../eval/vector-v3-improvement/final-selection-lock.json)에 잠갔다. 문서 48,235개, 새 영어 원문 질문 91개와 그중 20개 한국어 번역에 대한 최종 점수는 이 커밋 시점에 아직 산출하지 않았다. 원문 91개는 ServerFault 9개, Ask Ubuntu 59개, Super User 23개이며 모두 홈서버 장애 복구 기록인 것은 아니다.

기준선 MiniLM, BM25, 선택한 임베딩 단독, 선택한 전체 조합을 같은 후보 풀에서 비교한다. 최종 점수를 보고 다른 조합을 다시 고르지 않는다. 커뮤니티 중복 질문 ID를 정답으로 사용하는 검색 단계 시험이며 LLM Judge로 답변의 정오를 채점하는 시험이 아니다.

[평가 방법·근거·재현 절차](../eval/vector-v3-improvement/README.md), [최초 계획](../eval/vector-v3-improvement/protocol.json), [변경 기록](../eval/vector-v3-improvement/development-amendments.json), [선택 전후 상태 기록](../eval/vector-v3-improvement/pretest-publication.json)을 함께 공개한다. 원문 게시물 전체와 모델 가중치·운영 로그·비밀값은 공개 자료에 포함하지 않는다.

개발 실험의 문항별 지표 14,924개는 외부 IR 라이브러리로 교차 계산해 일치했다. 관련 테스트 22개가 통과했다. 이는 계산 검증 기록이며 독립 표본 14,924개라는 뜻은 아니다. 유료 API 호출은 없고 운영 검색 설정은 변경하지 않았다.
