# Vector retrieval v1 — controlled, source-grounded diagnostic

[결과·근거·면접 가이드](../../docs/VECTOR-EVAL-RESULTS-2026-11-17.md)

40개 합성 문서(알람 20 + 해결 20), 60개 정답 있는 질문(20유형 × 3표현), 8개 정답 없는 질문을 제공한다. 공식 문서·공개 이슈 16개를 근거로 새로 작성했으며 자연 발생 운영 사건이나 공식 BEIR 벤치마크가 아니다. 질문과 관련성 매핑은 한 작성 컨텍스트에서 구성했고 사람 독립 검수는 없다.

- `dataset.json`: 문서, 질의, 관련 문서 ID, 사례별 관련성 이유.
- `sources.json`: 근거 URL, 지원하는 주장, 원문 스냅샷 해시와 수집 제한.
- `protocol.json`: 결과 확인 전에 정한 방법·지표·범위.
- `runs/initial/`: 모델 식별, 고정 입력 해시, 합성 문서의 임베딩, pgvector 순위, 질문별 결과와 집계.
- `offline-verification.json`: 저장된 공개 자료로 재계산한 확인 결과.

원시 외부 매뉴얼 사본, 실패한 첫 파싱 시도의 작업 자료, 운영 환경 주소는 공개하지 않는다. 여기의 문서·질의·벡터·순위는 이번 평가용 합성 자료라서 별도로 공개한다.

## 모델이나 DB 없이 결과 확인

Python 3.10+와 표준 라이브러리만 필요하다.

```bash
python3 scripts/verify_vector_retrieval_artifacts.py
python3 -m unittest discover -s scripts/tests -p test_vector_retrieval.py -v
```

첫 명령은 데이터·코드·실행 파일 해시, 임베딩 108개, pgvector 순위 136개, 결과 272개와 지표를 검증한다. 의미 관련성 라벨의 진실성을 증명하는 명령은 아니다.

## 새 모델/DB 실행

Ollama의 `all-minilm:latest`와 pgvector가 필요하다. 기존 결과는 보존하고 별도 체크아웃에서 `runs/initial`을 다른 이름으로 옮긴 뒤 새 실행을 만든다. 운영 DB를 사용하지 않는다. 평가기는 `vector_eval` 데이터베이스를 가진 격리 컨테이너에 Docker exec로 접속하며 호스트 DB 연결 문자열을 받지 않는다.

```bash
# 격리 평가용 로컬 pgvector 이미지를 준비한 환경에서 실행
# 이미지 태그·버전이 달라지면 새 실행의 환경 차이로 기록해야 한다.
docker run --rm -d --name monitoring-vector-eval-20261117 \
  --network none --memory 256m --cpus 1 --pids-limit 128 \
  --tmpfs /var/lib/postgresql/data:rw,size=128m \
  -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=vector_eval pgvector/pgvector:pg16

python3 scripts/eval_vector_retrieval.py freeze --endpoint http://localhost:11434
python3 scripts/eval_vector_retrieval.py run --endpoint http://localhost:11434

docker rm -f monitoring-vector-eval-20261117
```

실행기의 Docker 호출에는 작업 환경에서 사용하는 `rtk`가 필요하다. 오프라인 검증에는 필요 없다. 실행 전 컨테이너 준비 상태를 확인한다. 이 명령은 운영 서비스 설정을 바꾸지 않는다.

본 결과에서는 BM25 Recall@5가 56/60으로 가장 높았으나, 같은 데이터로 튜닝한 뒤 최종 성능이라고 주장하면 안 된다. 최종 응답·원인 진단·복구 성공률과도 구분한다.
