# 커버리지와 근거 연결

40개 중 개발 5개, 테스트 35개다. 알람 조사 21개와 일반 질문 19개이며, 질문 변형은 원래 장애와 같은 family로 묶었다. 수치·관측의 정확성, 직접 원인과 미확인의 구분을 평가한다.

| 사례 묶음 | 근거 | 정답의 근거와 범위 |
|---|---|---|
| CPU 지속/회복, RAM/RSS, disk 공간/IO, GPU 온도/VRAM | USE Method + 실제 Prometheus 규칙 | 재생된 실제 PromQL 값. 프로세스별 궁극적 원인까지 증명하지 않음 |
| 외부 HTTP 장애/회복, DNS 지연, 인증서 | SRE 가설 검증 + 실제 PublicSite 규칙 | probe 상태/단계별 시간, 인증서 timestamp, 갱신 실패 로그. HTTP 502만으로 upstream 내부 원인 확정 금지 |
| SSH 불가, systemd unit 실패 | 실제 운영 규칙 | probe/failed unit 관측. SSH 불가만으로 방화벽 원인 확정 금지 |
| 백업 지연/실패, 알림 전송 실패 | 실제 운영 규칙 | 마지막 성공 timestamp, exit code, 실패 counter. 복원 성공·종료 코드의 근본 원인은 별도 |
| OOM, Jellyfin 트랜스코딩, 시계 | USE + 실제 운영 규칙 | OOM counter·RAM, CPU core 사용량과 인코딩 로그, NTP offset/sync. 보이지 않는 kernel 로그의 희생 프로세스는 unknown |
| 포트 bind, 환경변수, DB lock/slow query, reload YAML | SRE 증거 기반 가설 확인 | fixture 로그의 직접 실패 내용. 느린 쿼리만 보고 누락 인덱스를 확정하지 않음 |
| Docker target port 오류/정상 | AIOpsLab 실제 target-port 문제 정의 + Docker inspect | Docker 매핑과 앱 listen 로그를 모두 읽고 일치 여부 비교. 원본 K8s 벤치마크 재현이 아닌 명시적 변형 |
| 이미지·상태·health 질문 3개 | 실제 Docker snapshot + 공식 inspect 문서 | 수집 시각의 선택 필드. live incident 데이터는 아님 |
| unknown metric, inventory 불가, 부분 복구, 로그 지시문 | SRE의 관측/가설 분리 + 통제 대조 | 없음/조회 실패/정상 구분, 로그 속 지시와 실제 실패 내용 구분 |

공식 참고 자료: [Google SRE troubleshooting](https://sre.google/sre-book/effective-troubleshooting/), [USE Method](https://www.brendangregg.com/usemethod.html), [Prometheus rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/), [rule unit testing](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/), [Docker inspect](https://docs.docker.com/reference/cli/docker/container/inspect/), [AIOpsLab](https://github.com/microsoft/AIOpsLab).

운영 규칙 58종 중 19종의 표현식을 재생한다. 이는 규칙 종류 수이지 전체 사고 또는 질문의 33%를 해결한다는 뜻이 아니다. 이전 30일 운영 이벤트 감사에서 PublicSiteSlow 95행, PublicSiteDown 34행이 많았으므로 공개 사이트 관측을 우선했다. 이벤트 행은 독립 사고 건수가 아니고, 확인된 해결 원인이 연결된 데이터도 아니므로 발생 빈도 가중 정확도로 사용하지 않았다.

자주 보였던 ContainerKilled 이벤트와 이 데이터셋의 시작 실패/재시작/호스트 OOM 사례는 완전히 같은 규칙 검증이 아니다. 재시작 횟수의 시간 차분, cgroup 제한 OOM과 호스트 OOM 분리, 삭제된 컨테이너 이력, 복구 뒤 서비스 건강성은 추가 대상이다. 네트워크 경로·DB 실행계획·디스크 물리 오류·백업 복원과 같은 관측이 없는 영역까지 포함했다고 주장하지 않는다.

데이터셋 품질을 더 높이려면 실제 사고마다 기준 시각, 관측 원본, 가설/반증, 변경 이력, 복구 후 검증, 최종 원인과 독립 검토자를 함께 기록해야 한다. 지금의 40개 통제 사례를 계속 늘리는 것만으로 실운영 정확도가 자동 입증되지는 않는다.
