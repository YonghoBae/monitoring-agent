# 검색 원인 진단 자료

[결론·실험 범위·한계](../../docs/VECTOR-CAUSE-DIAGNOSIS-2026-11-18.md)를 먼저 읽는다. v3 최종 시험을 변경하지 않은 사후 진단이며 새로운 독립 시험이 아니다.

숫자 재검증:

```bash
python -m venv .venv-vector
.venv-vector/bin/pip install -r scripts/requirements-vector-verify.txt
.venv-vector/bin/python scripts/verify_vector_diagnosis.py
```

공개 순위에서 외부 IR 구현으로 지표를 재계산하고 집계·paired cluster 구간·문서 표현 비교·파일 해시를 확인한다. 원문 게시물, GPU, 모델, API 키가 필요 없다. 모델 추론 및 정답의 적합성을 독립 검증하는 명령은 아니다.

`plan.json`은 최초 진단 조건과 원본 파일 해시, `amendments.json`은 결과 확인 후 추가한 MiniLM 본문 대조·문서 수 대조 및 CPU 계산 수정 기록이다. `runner-initial.py`는 최초 GPU 진단에 쓰인 코드 증거이며 실행 진입점이 아니다. `runner-revision.json`은 수정 전후 해시다. 원래 입력 원문·모델 벡터는 공개하지 않으며 원문부터 추론을 재실행하려면 v3의 로컬 입력 캐시와 고정 가중치가 필요하다.

전체 후보 실험과 `pool5000` 축소 후보 실험, `document-probe`의 정답 포함 고정 후보 표현 비교를 서로 같은 정확도처럼 비교하지 않는다. 특히 문서 표현 실험의 후보에는 알려진 정답을 강제로 포함했다.

질문 본문은 수집 당시 상태라 사후 편집·답변 단서가 없다고 보장하지 않는다. 정답 제목 문자열 일치 네 질문을 제외한 민감도 결과를 함께 남겼다. 정답표는 변경하지 않았다. 사례 검토는 동일 에이전트의 분석이며 독립 관련성 판정이 아니다.
