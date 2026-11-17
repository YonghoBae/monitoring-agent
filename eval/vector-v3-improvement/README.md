# 실사례 검색 개선 실험

기존 MiniLM 검색과 다국어 임베딩·리랭커를 비교하는 **검색 단계 평가**다. 생성 답변의 정답률이나 에이전트의 원인 진단 성공률을 측정한 실험은 아니다. 최종 수치는 [결과 보고서](../../docs/VECTOR-IMPROVEMENT-RESULTS.md)에 정리한다.

## 데이터와 선택 절차

- 개발: 실제 질문 문서 5,000개, 최근 Unix 영어 질문 100개, 기존 Unix 질문의 한국어 번역 32개와 영어 원문 32개. 전체 문서 중 개발 정답을 포함하고 나머지는 ID 해시로 선택했다. 모델 선택용 축소 풀이다.
- 선택 기준: 최근 영어 nDCG@10과 한국어 대조군 nDCG@10을 각각 50% 반영한다. 실제 트래픽 비율을 추정한 가중치가 아니라 이번 실험의 제품 우선순위다.
- 새 평가: ServerFault 9개, Ask Ubuntu 59개, Super User 23개의 실제 중복 질문 91개. 커뮤니티가 연결한 원 질문 ID를 정답으로 삼았다. 그중 ID 해시로 선택한 20개 제목을 한국어로 번역했다.
- 최종 후보 문서: 48,235개. 모든 방법이 같은 후보 풀에서 검색하며 질문 자기 자신은 제외한다.
- 후보 문서는 영어다. 한국어 대조군은 **한국어 질의 → 영어 사례 검색**을 측정한다. 한국어 질의 → 한국어 운영 기록의 정확도로 바꾸어 해석하면 안 된다. BM25는 Unicode 단어 토큰, lowercase, k1=1.2/b=0.75를 쓰며 번역·형태소 분석·stemming을 하지 않는다.
- 새 평가 문항과 한국어 번역은 새 후보 모델의 첫 개발 점수가 산출되기 전에 확보·동결했다. 번역 동결은 14:04:39 UTC, 첫 E5 개발 점수 산출은 14:05:14 UTC다. 첫 임베딩 계산과 번역 준비가 병행됐으므로 모든 준비가 추론 시작 전 끝난 엄격한 사전등록이라고 주장하지 않는다. 개발 결과로 선택한 조합은 `final-selection-lock.json`에 잠근 후 최종 평가한다. 최종 결과를 보고 조합을 다시 선택하지 않는다.
- 같은 출처 질문의 번역, 동일 정답 문서를 공유하는 질문을 묶어 paired cluster bootstrap 2,000회로 차이의 95% 구간을 계산한다. 영어 원문 91개는 알려진 정답 공유 관계로 80개 묶음이다. 이 조치가 모든 의존성이나 표본 편향을 제거하지는 않는다.

`protocol.json`이 최초 계획이고 `development-amendments.json`이 변경 내역이다. 최초 계획을 사후 수정하여 변경을 감추지 않는다. 소스 부족에 따른 추가 사이트, 리랭커 top20 선별 후 top50 확장, 1개 최종 후보의 전체 인덱싱 시간 예산, 군집 신뢰구간 변경을 기록했다.

## 후보 선정 근거

| 후보 | 이 실험에서 확인한 역할 | 공식 출처 |
|---|---|---|
| all-minilm | 현재 서비스의 384차원 기준선 | [Ollama](https://ollama.com/library/all-minilm) |
| multilingual-e5-small | 비교적 작은 다국어 임베딩, 384차원 | [모델 카드](https://huggingface.co/intfloat/multilingual-e5-small) |
| BGE-M3 | 다국어 dense 임베딩, 1,024차원 | [모델 카드](https://huggingface.co/BAAI/bge-m3) |
| Qwen3-Embedding-0.6B | instruction을 사용하는 다국어 임베딩, 1,024차원 | [모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) |
| BGE-reranker-v2-m3 | query-document 관련도 분류 리랭커 | [모델 카드](https://huggingface.co/BAAI/bge-reranker-v2-m3) |
| Qwen3-Reranker-0.6B | 공식 yes/no logit 방식 리랭커 | [모델 카드](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) |

4 GiB GPU에서 로컬 실행 가능한 크기, 한국어·영어 지원, 공식 사용법, 라이선스와 고정 가능한 가중치를 기준으로 세 임베딩과 두 리랭커를 골랐다. 시장 전체의 최적 모델을 찾는 전수 비교는 아니다. 유료 API, 더 큰 Qwen 모델, 양자화, BGE의 sparse/ColBERT 기능은 이번 비교 범위에 없다.

모델별 공식 pooling/prefix를 적용한다. E5의 `query:/passage:`와 유사 질문 검색에 맞는 `query:/query:`를 별도 조건으로 비교했다. BGE는 CLS, Qwen 임베딩은 마지막 토큰과 query instruction을 사용한다. Qwen 리랭커는 자유 형식 답변을 생성하거나 시험을 채점하지 않는다. **채점 기준은 외부 커뮤니티 정답 ID와 IR 지표**다.

## 입력과 자원 조건

- 문서 입력은 제목 + 줄바꿈 + 본문이다. 임베딩은 모델별 tokenizer 기준 최대 256토큰, 리랭커는 최대 512토큰이다. 같은 원문도 tokenizer에 따라 잘리는 위치가 다르므로 순수한 모델 구조만의 비교라고 주장하지 않는다.
- GTX 1050 Max-Q 4 GiB, Torch 2.6.0/cu124, Transformers 4.51.3. 각 모델은 정확도 계산 전에 같은 32개 smoke 입력으로 FP32/FP16을 검사하고 정상 출력 중 빠른 정밀도를 고른다. 대형 모델 batch 2, E5 batch 4다. 최적 처리량 탐색 결과는 아니다.
- 리랭커는 기준선과 개발에서 선택한 임베딩의 동일한 top20 후보를 각각 재정렬한다. 우세한 조합에서 dense top50과 dense25+BM25 25의 중복 제거 합집합을 비교한다. 합집합은 중복 때문에 50개보다 적을 수 있다.
- 앞부분/뒷부분 벡터의 최대 유사도도 별도 조건으로 측정한다. 이는 전체 본문을 빠짐없이 나누는 chunking이 아니다.
- 같은 모델·입력·설정의 pair 점수는 캐시를 재사용한다. 최종 지연시간은 캐시를 끄고 다시 계산한다. 이 수치는 로드된 리랭커의 후보 처리 시간이며 API 전체 지연이나 답변 LLM과 동시 실행하는 시간은 아니다.
- 전체 문서 인덱싱은 개발에서 고른 한 임베딩만 수행한다. 모델 교체·DB 스키마 변경·운영 배포는 이 실험에 포함하지 않는다.

## 출처와 학습 중복

기존 Unix 데이터는 [CQADupStack 원 저자 저장소](https://github.com/D1Doris/CQADupStack) / [MTEB CQADupstackUnixRetrieval](https://huggingface.co/datasets/mteb/cqadupstack-unix)의 실제 질문과 중복 관계다. 새 문항은 [Stack Exchange API](https://api.stackexchange.com/docs/advanced-search)의 closed/duplicate 질문과 `closed_details.original_questions`에서 얻었다. 수집 규칙, 제외 내역, 원문 URL·ID·생성 시각은 `holdout*/` manifest에 있다.

`holdout-source-audit.json`에 따르면 새 91개 질문은 109개 정답 연결, 98개 고유 정답 문서를 갖는다. 정답 문서 98개 모두 답변이 있고 60개에는 채택 답변이 있다. 새 질문 중 채택 답변이 있는 문서로 연결되는 것은 59개다. 답변 채택은 게시물 metadata이며 실제 서버 복구를 독립적으로 검증한 증거는 아니다. 정규화된 질문 제목이 정답 제목과 정확히 같은 문항은 0개다. 답변 본문은 검색 입력에 넣지 않았다.

현재 MiniLM의 공개 학습 자료와 기존 Unix 문항 사이에 겹침이 있었으므로 기존 자료의 점수를 독립 검증으로 사용하지 않는다. 새 91개 원문의 생성 시각은 2025-08-13부터 2026-10-28까지다. 새 후보 다섯 모델의 고정된 실제 가중치 파일은 늦어도 2025-06-03에 존재했고, 내려받은 파일 SHA-256이 공식 LFS OID와 일치함을 확인했다. 저장소의 최신 metadata 수정일을 가중치 생성일로 오해하지 않는다. 이 시간 순서는 직접적인 새 질문 암기 가능성을 줄이는 근거이며 오래된 관련 문서나 다른 형태의 유사 학습 데이터가 없다는 증명은 아니다.

## 재검증

숫자 검증은 GPU, 모델 파일, API 호출 없이 공개된 ID·qrels·순위만으로 실행할 수 있다.

최종 공개 파일의 SHA-256 목록은 `artifact-sha256.json`에 있다. 검증기는 이 목록도 확인한다. 별도의 새 CPU 환경에서 23,704개 지표 값과 20개 테스트가 통과한 기록은 `clean-environment-verification.json`이다. 이는 모델 추론을 다시 수행한 기록이 아니다. 숫자 재검산에는 RTK가 필요 없지만 전체 실행 조정·임시 DB 스크립트의 subprocess는 RTK 명령을 사용한다.

```bash
python -m venv .venv-vector
.venv-vector/bin/pip install -r scripts/requirements-vector-verify.txt
.venv-vector/bin/python scripts/verify_vector_improvement_results.py
.venv-vector/bin/python scripts/analyze_vector_improvement_errors.py
```

`ir_measures`로 모든 문항별 지표를 교차 계산하고 평균, 선택 점수, 신뢰구간, 후보·정답 ID, 자기 자신 제외, 선택 잠금과 코드 해시를 검사한다. 동일 bootstrap 함수를 다시 실행하는 것은 계산 재현 확인이며 통계 방법 자체에 대한 독립적인 사람 검수가 아니다.

`Vector evidence (CPU)` GitHub Actions workflow는 같은 숫자 재검증과 모델을 요구하지 않는 20개 테스트를 실행한다. GPU·Torch·모델 파일·LLM API 키를 사용하지 않는다. 이것은 공개된 순위에서 점수를 재계산하는 검사이며 모델 추론 자체를 다시 실행하는 검사는 아니다. 로컬 전체 관련 테스트는 pair-cache 검사 2개를 더한 22개다.

모델 추론 재실행에는 로컬 원문 캐시와 모델 다운로드가 필요하다. 원문 수집은 시간이 지나면 편집·삭제로 달라질 수 있다. 공개 저장소에는 제3자 게시물 전체, 모델 가중치, 운영 로그나 비밀값을 배포하지 않으며, manifest의 원문 해시로 동일 입력 여부를 확인한다. 따라서 공개 숫자 재검증과 원문부터 완전 동일한 모델 재실행은 구분해야 한다.

주요 스크립트:

- `prepare_vector_improvement.py`, `extend_vector_holdout.py`: 개발 풀과 새 문항 수집
- `audit_vector_holdout_sources.py`: 실제 정답 연결, 채택 답변 metadata, 제목 일치 여부와 저자/라이선스 출처 점검
- `audit_vector_duplicate_links.py`: 최종 점수를 보기 전에 공개 중복 연결을 별도 동결한다. 최종 정답 ID에는 없지만 같은 중복 연결 묶음에 있는 검색 결과를 보조 진단에서 표시한다. 여러 질문을 거친 연결은 관련성의 완전한 판정이 아니므로 정답을 늘리거나 주 점수를 다시 채점하지 않는다.
- `download_vector_models.py`, `vector_model_candidates.py`: 고정 가중치, 공식 입력 처리, GPU 프로파일
- `eval_vector_improvements.py`, `eval_e5_symmetric.py`: 임베딩·입력 조건 비교
- `eval_cached_vector_reranker.py`, `run_vector_improvement_stages.py`: 리랭커 비교와 최종 선택 잠금
- `eval_full_vector_improvements.py`: 같은 전체 문서 풀에서 최종 비교
- `verify_vector_improvement_results.py`: 공개 순위/지표 재검증
- `analyze_vector_improvement_errors.py`: 후보 누락과 순위 실패 구분
- `verify_vector_improvement_pgvector.py`: 별도 임시 PostgreSQL에서 exact cosine 순위 확인. ANN 인덱스나 운영 API 검증은 아니다.
- `probe_vector_pipeline_runtime.py`: 최종 평가 후 ID 해시로 고른 영어 3개·한국어 3개 요청에서 모델을 순서대로 로딩하여 메모리 안의 전체 문서 검색과 리랭킹까지 실행한다. 모델 교대 로딩 시간을 포함하지만 DB/API/답변 LLM은 포함하지 않는다. 6개 표본으로 안정적인 p95를 주장하지 않는다.
- `eval_native_vector_regression.py`: 기존 한국어 합성 fixture의 20개 문제 계열·40문서·60개 정답 있는 질의에 고정된 새 임베딩을 적용하는 부록이다. 문서 40개 전체와 해결 기록 20개 필터를 각각 비교한다. 모델 선택과 주 실사례 점수에 사용하지 않으며 리랭커·무정답 판별은 검증하지 않는다. 데이터가 작고 작성된 정답이므로 실제 한국어 운영 기록의 성능 증거로 사용하지 않는다.

## 해석 한계

91개가 모두 홈서버 장애 복구 사례는 아니다. ServerFault는 9개이고 Ubuntu/Super User에는 데스크톱 부팅, 패키지, WSL 등 운영과 인접한 질문도 포함한다. 제목만으로 검색하므로 본문에 있는 조건이 빠진 문항이 있다. 커뮤니티 중복 표시는 관련 문서를 모두 열거한 완전한 정답 집합이 아니다. 한국어는 실제 사용자가 남긴 한국어 운영 로그가 아니라 영어 제목의 번역 대조군이며 독립적인 사람 번역 검수를 받지 않았다. 영어·한국어를 합쳐 111개의 독립 사례로 주장하지 않는다.

실제 한국어 알람/해결 기록, 메타데이터 필터, 무정답 질의, 답변의 근거 충실도, LLM 동시 상주, 전체 API 지연은 운영 채택 전에 별도로 검증해야 한다. 이번 결과만으로 에이전트 전체 정확도나 모든 홈서버 환경에 대한 성능을 주장할 수 없다.

최종 점수를 보기 전에 본 작업 에이전트가 한국어 번역 20개를 영어 원제와 다시 대조한 기록은 `translation-review.json`에 있다. 버전·경로·제품명·질문 의도에서 중대한 차이는 발견하지 않았고 입력 변경은 0건이다. 원제부터 정보가 부족한 질문은 그대로 유지했다. 같은 에이전트의 재확인이므로 독립 검수나 사람 검수를 대신하는 증거로 취급하지 않는다.
