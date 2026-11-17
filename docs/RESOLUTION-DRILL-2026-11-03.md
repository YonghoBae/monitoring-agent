# 검증된 해결 기록 저장 결과

## 결과

`resolution_record`가 **0건에서 1건**으로 증가했다. SQL로 해결 행을 직접 삽입하지 않고 기존 `ResolutionFeedbackService.recordOutcome()`를 실행했다. 실제 PostgreSQL 및 Ollama `all-minilm` 임베딩을 사용했다.

| 항목 | 값 |
|---|---|
| 해결 기록 ID | `1` |
| 알람 ID | `931` |
| 알람 이름 | `SyntheticDrillHttpUnavailable` |
| 결과 | `RESOLVED` |
| 벡터 문서 ID | `c4777830-e8e5-4637-abcf-f1794dcfac68` |
| 임베딩 차원 | `384` |
| 테스트 식별자 | `resolution-drill-c34be847e784` |
| 출처 | `synthetic=true`, `source=controlled-drill` |

알람 이름·레이블·해결 본문 모두 테스트임을 표시한다. 해결 문서 자체에도 `[SYNTHETIC DRILL]`과 실제 복구 증거가 들어 있다.

## 실제 관측한 장애와 조치

운영 컨테이너 대신 임시 Nginx 컨테이너 하나를 만들었다. HTTP 포트를 외부에 공개하지 않았고, 모니터링 네트워크에서 Blackbox Exporter가 검사했다.

1. **정상**: 2026-11-03 00:35:54.139 KST, `probe_success=1`.
2. 임시 컨테이너를 중지했다.
3. **실패**: 00:35:54.518 KST, `probe_success=0`.
4. 같은 컨테이너를 `docker start`로 복구했다.
5. **복구**: 00:35:55.734 KST, `probe_success=1`. 추가 검사도 성공했다.
6. 관측 시각·대상·복구 명령·검사 결과를 해결 본문에 기록한 뒤 기존 피드백 서비스를 호출했다.
7. 실행 후 임시 HTTP 컨테이너는 제거했고, 남아 있는 drill 컨테이너가 없음을 확인했다.

## 검증

- 기본 Java 테스트: **54개 통과**, 실패·오류·건너뜀 0개. 기본 실행에서 live drill이 제외됨.
- 실제 DB 통합 검증: **1개 통과**.
- 해결 행, 알람의 해결 상태, 해결 기록 연결, 실제 벡터 행 및 384차원 임베딩 확인.
- 기존 `AlertVectorService.searchSimilar()`의 상위 5개 결과에서 새 해결 문서 검색 성공.
- 같은 알람에 다시 피드백을 주면 중복 저장하지 않는 것 확인.
- 독립 검토에서 발견한 실행기 정리 문제 수정: 고유 컨테이너 이름, 180초 제한, finally 제거, SIGTERM 처리. timeout 정리 회귀 테스트는 수정 전 실패→수정 후 통과.
- 최종 운영 상태: 활성 경보 0건, Prometheus 수집 실패 0건, Loki ready, 모니터링 앱 running 및 재시작 0회.

## 무엇이 검증됐고 무엇이 남았는가

**검증됨:** 실제로 복구한 사례를 기존 해결 저장 서비스가 DB와 RAG에 넣고 다시 검색할 수 있다.

**미검증:** LLM이 운영 장애를 스스로 진단·조치·검증하는 전체 과정. 이번 복구는 Codex 검증 실행기가 수행했다. 실제 Alertmanager 경보 발화 및 Discord 피드백 수신 경로도 이번 시험 범위가 아니다. 외부 메시지는 전송하지 않았다.

운영 알람의 해제만으로 해결 테이블이 자동 채워지지 않는 기존 구조는 그대로다. 실제 사례는 원인·조치·복구 증거를 확인한 뒤 피드백 경로로 저장해야 한다. 임의의 기존 알람을 해결됐다고 일괄 표시하지 않았다.

테스트 사례도 현재 기본 RAG 검색 대상에 포함된다. 테스트 출처는 명시돼 있으나 별도 검색 필터는 아직 없다. 검색 품질 비교나 자율 복구 성과를 계산할 때 운영 성공 사례로 집계하면 안 된다.

## 재실행

프로젝트 루트에서 `rtk proxy python3 scripts/resolution_drill.py --execute`.

명시적 `--execute`가 없으면 실행하지 않는다. 재실행마다 **실제 DB에 새로운 테스트 해결 기록 1건**이 추가된다. 기존 DB·Ollama·Blackbox 컨테이너와 로컬 `eclipse-temurin:21-jdk-alpine`, `nginx:alpine` 이미지가 필요하다. DB DDL은 `validate`만 사용한다.

Python 회귀 테스트: `rtk proxy python3 -m unittest discover -s scripts/tests -v`.

남은 경미한 검증 제약: 중복 방지 검증이 전체 해결 행 수를 비교하므로 시험 중 다른 사용자가 해결 피드백을 저장하면 테스트가 오탐 실패할 수 있다. 서비스의 실제 중복 검사는 해당 알람 기준이다.
