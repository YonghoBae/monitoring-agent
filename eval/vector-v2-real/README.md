# 실제 기록 기반 검색 평가

CQADupStack Unix의 실제 StackExchange 질문 47,382건, 질문 제목 1,072개, 기존 중복 질문 관련성 판정 1,693개를 사용한다. 합성 문서와 LLM Judge를 사용하지 않는다. 정답은 **같은 문제를 다룬 기록**이며, 해결 방법의 정확성이나 자동 복구 성공을 뜻하지 않는다.

출처는 [원 저자 저장소](https://github.com/D1Doris/CQADupStack), [원 논문](https://doi.org/10.1145/2838931.2838934), [BEIR](https://github.com/beir-cellar/beir), [실제 내려받은 MTEB 스냅샷](https://huggingface.co/datasets/mteb/cqadupstack-unix/tree/3197b09145642430d9db451fcdc1e1987e54d74c)이다. 원본 텍스트는 재배포하지 않으며, `source-manifest.json`의 고정 리비전과 SHA-256으로 내려받아 확인한다. 원 논문과 미러의 라이선스 표기가 다르므로 미러 표기만으로 원문 이용 조건을 단정하지 않는다.

## 결과와 범위

- [결과 및 면접용 설명](../../docs/VECTOR-REAL-EVAL-RESULTS-2026-11-17.md)
- `protocol.json`: 첫 점수 계산 전 고정한 실험 조건. 외부 사전등록은 아니다.
- `protocol-amendment.json`: 점수 계산 전 발견한 모델 최대 컨텍스트 512와 **실제 실행 컨텍스트 256**의 차이를 기록한 메타데이터 정정. 요청 옵션·문서·정답·비교 방법은 바꾸지 않았다.
- `query-subsets.json`: 운영 관련 제목 정규식으로 고른 220개 질문과 해시 순으로 선택한 한국어 번역 대상 32개 ID.
- `korean-queries.json`: 원문 질문 제목의 한국어 번역. 같은 정답 관계를 사용한다. 자연 발생 한국어 운영 기록이나 독립적인 사람의 번역 검수를 대신하지 않는다. 각 항목의 원문 링크를 표시한다.
- `source-case-audit.json`: 사전 선택한 32개 질문의 정답 후보 48건에 대해 원문과 채택 답변 유무를 별도로 확인한 기록. 답변 본문은 임베딩·채점에 사용하지 않는다.
- `training-overlap-audit.json`: 공개 학습 제목 쌍 304,525개와 대조한 결과. 역사적 질문 498개에서 정확한 제목 쌍 중복을 발견했으므로 이 점수를 독립 일반화 성능으로 사용하지 않는다.
- `recent-control/`: 위 문제를 발견한 후 별도 규칙을 고정하고 수집한 2025~2026년 실제 질문 100개, 기존 커뮤니티 정답 관계 109개, 후보 47,463개에 대한 추가 시험. 확인한 학습 제목 쌍 일치는 0개지만 모든 학습 출처와의 비중복을 증명하지는 않는다.
- `runs/real-v1/`: 상위 100개 검색 결과 ID, 질문별 점수, 집계, 검증 결과. 원문·임베딩 캐시·운영 서버 정보는 포함하지 않는다.

## API 호출 없이 점수 검증

원문 스냅샷 다운로드에는 인터넷이 필요하다. 다운로드 후 검색 순위에 대한 점수 재계산은 모델 API 없이 실행한다.

```bash
python3 -m venv .venv-vector
.venv-vector/bin/pip install -r scripts/requirements-vector.txt
.venv-vector/bin/python scripts/prepare_real_vector_eval.py
.venv-vector/bin/python scripts/verify_real_vector_retrieval.py
.venv-vector/bin/python -m unittest discover -s scripts/tests -p test_real_vector_retrieval.py -v
```

검증기는 모든 상위 100개 결과가 해당 후보 집합에 속하는지, 중복이 없는지, 누락된 질문이 없는지 확인한다. 질문별 지표를 직접 재계산하고 `ir_measures`/`pytrec_eval`과 비교한다. 집계 및 paired bootstrap도 재계산한다. 이는 산술·구현 검증이며 정답의 완전성이나 현장 대표성을 보증하지 않는다.

## 임베딩·검색 재실행

`all-minilm:latest`의 정확한 다이제스트는 `protocol.json`에 있다. 같은 이름이어도 다이제스트가 다르면 실행을 중단한다. 원본 공개 결과를 보존하고 별도 복사본에서 `runs/real-v1`을 이동한 뒤 실행한다. 내려받은 프로토콜을 다시 `freeze`하지 않는다.

```bash
OLLAMA_URL=http://localhost:11434 .venv-vector/bin/python scripts/eval_real_vector_retrieval.py embed
.venv-vector/bin/python scripts/eval_real_vector_retrieval.py score
.venv-vector/bin/python scripts/verify_real_vector_retrieval.py
```

전체 후보 47,382개 결과가 주 평가다. 5천·2만 후보는 모든 공개 정답 문서를 포함하고 해시 순으로 방해 문서를 추가한 통제 실험이다. 이는 공식 BEIR 부분집합이나 독립 테스트 분할이 아니다. 같은 질문에서 후보 규모 변화의 영향을 비교하는 용도다.

Dense는 정규화된 384차원 벡터의 정확한 코사인 순위다. BM25는 명시한 수식·토큰화로 직접 구현했으며 Elasticsearch/Lucene 공식 실행 결과가 아니다. RRF는 각 검색의 상위 100개를 동일 가중치와 k=60으로 결합한다. BM25는 전체 본문, Dense는 실제 256토큰 컨텍스트를 사용한다. 지연시간 비교용 벤치마크가 아니며 Spring AI 전체 요청 경로와 HNSW 검색을 실행한 것도 아니다.

## PostgreSQL 확인

`check_real_vector_pgvector.py --container <이름>`은 `monitoring-vector-real-eval-`로 시작하는, 네트워크·호스트 바인드 마운트·포트 공개가 없는 임시 컨테이너만 허용한다. 별도 `vector_eval` DB에 전체 벡터를 넣고 사전 선택한 영어 32개와 한국어 32개의 SQL 상위 10개 순위를 비교한다. 운영 DB에서는 실행하지 않는다. 컨테이너 생성·삭제는 명시적으로 수행해야 한다.

기존 `vector-v1`은 작은 합성 진단 시험으로 그대로 보존했다. 두 평가의 언어·문서·정답이 달라 점수 차이를 그대로 개선율로 계산하면 안 된다.

## 최근 사례 결과를 인터넷 없이 재검증

의존성이 설치돼 있으면 아래 명령은 공개된 ID·정답 관계·순위 파일만 사용한다. 원문 다운로드, Ollama, LLM Judge가 필요 없다.

```bash
.venv-vector/bin/python scripts/eval_recent_vector_control.py verify
```

최근 사례의 원문은 StackExchange API에서 수집한 시점의 응답을 로컬 캐시에 고정했다. 공개 파일에는 각 원문 URL·질문 작성일·정답 대상 ID·캐시 SHA-256을 남겼다. **고정 원문 캐시는 재배포하지 않으므로 외부에서 완전히 동일한 입력으로 임베딩을 재실행하는 것까지 보장하지 않는다.** 공개 URL의 현재 내용이 수집 시점과 달라질 수 있다. 공개 파일만으로 가능한 것은 숫자 점수의 완전한 재계산이다. 역사적 MTEB 시험은 고정 원문 스냅샷을 내려받아 전체 재실행할 수 있다.

수집 코드는 `prepare_recent_vector_control.py`, 실행 및 숫자 검증 코드는 `eval_recent_vector_control.py`다. 최근 시험은 기존 결과에서 문제를 발견한 뒤 설계한 후속 실험이며 공식 BEIR 평가셋으로 소개하면 안 된다.
