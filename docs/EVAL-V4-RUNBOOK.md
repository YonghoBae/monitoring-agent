# 재현 방법

완료한 160답변과 원본 실행 소스는 [보관 자료](../eval/results/20261116-203700/README.md)에 있다. 현재 `eval/v4/dataset.json`은 범주형 정답 한 값을 정정한 revision 4.1이다. 아래 명령은 현재 버전의 새 실행이며, 원래 점수를 재현하려면 보관된 원본 입력/소스를 사용한다. 원답의 채점 재현은 보관 폴더 안내를 따른다.

비교에는 Java 21, Python 3.12, Docker, 로컬에 준비된 `prom/prometheus:v2.53.0`, pi CLI 1.5.2, 도구 호출을 지원하는 Ollama 모델이 필요하다. 이 서버의 Python에는 PyYAML이 있고 `.venv-eval`에는 `scripts/requirements-eval.txt`의 parser가 있다. 라이브 관측·LLM 비교는 일반 `test`에서 실행되지 않는다.

고정된 `eval/v4/dataset.json`으로 실행하면 입력이 재현된다. `build_eval_v4.py`는 외부 원문과 현재 운영 규칙·컨테이너 상태를 다시 읽으므로 **새 데이터 버전 생성**이다. 기존 점수를 재현할 때 실행하지 않는다. 현재 수집 URL/컨테이너 선택은 이 홈서버용으로 명시되어 있다.

```bash
rtk proxy env RUN_DOCKER_INSPECT_TEST=1 RUN_NUMERIC_FIXTURE_TESTS=1 EVAL_PROMQL_PYTHON="$PWD/.venv-eval/bin/python" PYTHONPATH="$PWD/.venv-eval/lib/python3.12/site-packages" ./gradlew test --no-daemon
rtk proxy env RUN_NUMERIC_FIXTURE_TESTS=1 PYTHONPATH="$PWD/.venv-eval/lib/python3.12/site-packages" python3 -m unittest discover -s scripts/tests
rtk proxy env PYTHONPATH="$PWD/.venv-eval/lib/python3.12/site-packages" python3 scripts/validate_eval_v4.py
rtk proxy python3 scripts/run_harness_comparison.py --phase dev
```

개발 결과를 검토하고 소스·데이터를 고정한 후 다음 단계로 간다. 기본 모델/endpoint는 현재 홈서버 평가 환경의 설정이며 `EVAL_MODEL`, `EVAL_BASE_URL` 환경변수로 바꿀 수 있다. 같은 모델을 쓰는 비교를 동시에 실행하지 않는다.

```bash
rtk proxy python3 scripts/run_harness_comparison.py --phase test
```

`build/eval/campaign-*/manifest.json`은 모델 digest, pi 버전, 소스/데이터 SHA-256, 연결된 run 디렉터리를 기록한다. 소스나 데이터가 실행 전후에 바뀌면 결과를 채택하지 않는다. `comparison-*/results.jsonl`에는 원답, 예외, 시간, 실제 도구 관측이 있다. pi 원본 JSONL도 별도로 남는다.

원래 본 평가에는 `review-exclusions.json`을 함께 사용한다. Jellyfin encoding의 잘못된 원래 정답을 모든 조건에서 동일하게 제외하는 기록이다. 새 revision 4.1에는 정정된 unknown이 있으므로 이 원본 해시 전용 제외 파일을 적용하면 안 된다.

```bash
rtk proxy python3 scripts/score_harness_comparison.py build/eval/comparison-RUN_ID
rtk proxy python3 scripts/prepare_answer_review.py build/eval/comparison-RUN_ID
```

자동 추출하지 못한 필드는 `review-pending.json`에서 확인하고 **원답을 읽어** `answer-review.json`에 정확한 인용과 해석을 남긴다. 답하지 않은 항목도 검토 완료 상태로 표시한다. 정답이나 관측 trace의 문장을 원답에서 한 말처럼 인용하면 안 된다. `review_harness_answers.py`는 모든 필드의 검토 완료와 원답 내 인용 존재를 검사하지만 인용의 의미 해석은 별도 검토 대상이다.

```bash
rtk proxy python3 scripts/review_harness_answers.py build/eval/comparison-RUN_ID build/eval/comparison-RUN_ID/answer-review.json
rtk proxy python3 scripts/summarize_reviewed_comparison.py build/eval/comparison-RUN_ID
```

운영 장애 주입, 서비스 재시작, Discord 전송, DB 사고 해결 레코드 생성은 이 비교에 포함하지 않는다. 실제 복구 성능을 평가하려면 별도 격리 환경의 fault injection 및 복구 후 검증이 필요하다.

조회 도구는 `agent.discovery-tools-enabled=true` 또는 Spring 환경변수 `AGENT_DISCOVERY_TOOLS_ENABLED=true`로 **일반 대화와 focused 알람 조사**에 노출할 수 있다. 알람에서 사용하려면 `agent.investigation-mode=focused`도 필요하다. 기존 ReAct/Reflection 알람 경로에는 이 플래그만으로 도구가 추가되지 않는다. 기본값은 discovery=false, 기존 조사 경로이며 이번 작업에서 운영 설정을 활성화하거나 재배포하지 않았다. 일반 대화의 확장 도구 연결은 모델 비교 이후 회귀 검증한 후속 변경이다.
