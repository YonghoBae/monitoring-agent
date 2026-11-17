# 사례 근거의 의미와 추가 원문 대조

이 문서는 2026-11-16 최종 비교의 입력을 고정한 뒤 수행한 **출처 의미 검토**다. 아래 추가 문서를 모델 입력에 넣거나 정답·사례를 변경하지 않았다. 최초 수집 문서와 SHA-256은 `eval/v4/sources.json`, 공개 장애 구현과 라이선스는 `eval/v4/public-benchmark/`에 있다.

데이터셋 `provenance.sources`는 참고 문서 모음의 ID이며, 나열된 모든 문서가 해당 사례의 특정 수치나 장애 원인을 증명한다는 뜻은 아니다. 실제 사례별 적용 범위는 [커버리지 표](EVAL-V4-COVERAGE.md)와 아래 대조를 함께 읽어야 한다. 가령 AIOpsLab의 직접 구현을 변형한 것은 Docker target-port 두 사례이며, CPU·백업·DB 사례를 AIOpsLab 원본 문제로 간주하면 안 된다.

| 사례 | 공식 원문에서 확인한 내용 | 이 평가에서 증명하지 못하는 것 |
|---|---|---|
| `cert_expiry_soon`, 질문 변형 | [Certbot Standalone](https://eff-certbot.readthedocs.io/en/stable/using.html#standalone)은 HTTP 검증을 위해 80번 포트 바인딩이 필요하다고 설명한다. 포트 사용 충돌이라는 장애 유형에는 근거가 있다. | fixture의 정확한 날짜·7일·오류 로그는 원문 사고 기록이 아니다. 만료 임박만으로 포트 충돌을 추론할 수 없고 실제 갱신 오류를 읽어야 한다. |
| `postgres_autovacuum_bloat` | [PostgreSQL 15 routine vacuuming](https://www.postgresql.org/docs/15/routine-vacuuming.html#AUTOVACUUM)은 충돌하는 락이 일반 autovacuum을 중단시킬 수 있고, 반복 충돌로 완료가 방해될 수 있다고 설명한다. | 사례의 dead tuple 수나 특정 세션 원인은 통제 설정이다. wraparound 방지 작업에는 예외가 있으며, 로그 한 줄이 모든 bloat의 근본 원인까지 입증하지 않는다. |
| `mysql_slow_queries` | [MySQL 8.0 slow-query log](https://dev.mysql.com/doc/refman/8.0/en/slow-query-log.html)는 Query_time과 Lock_time을 초 단위로 정의한다. | 긴 Query_time만으로 인덱스 누락을 확정할 수 없다. 실행계획·락·데이터 분포 검증이 추가로 필요하다. |
| `alertmanager_reload_failed` | [Alertmanager configuration](https://prometheus.io/docs/alerting/latest/configuration/)은 YAML 설정과 파서 검증, `amtool check-config`를 설명한다. | 일반적인 설정 로딩 실패 문구만으로 YAML 문법 오류를 확정할 수 없다. 이 사례에서는 별도의 실제 파싱 오류 줄까지 조회해야 한다. |
| counter를 묻는 알림 실패·OOM·throttling | [Prometheus functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)는 rate의 초당 비율과 increase의 기간 증가량을 구분한다. [cAdvisor metrics](https://github.com/google/cadvisor/blob/master/docs/storage/prometheus.md)는 throttled periods counter를 설명한다. | rate 값을 그대로 15분 실패 횟수로 답하거나 기간 수를 초로 부르는 것은 올바른 답이 아니다. 숫자가 일치해도 요청 물리량과 단위가 다르면 오답이다. |
| `time_drift_ntp`, 질문 변형 | [node_exporter timex collector](https://github.com/prometheus/node_exporter/blob/master/collector/timex.go)는 sync_status의 1을 동기화, 0을 비동기화로 정의한다. | 수치 0을 맞히고 설명에서는 동기화됐다고 답하면 요청값 점수와 별개로 의미 해석 오류다. |

이 자료는 장애 유형의 타당성과 관측 해석을 뒷받침한다. 사례의 실제 발생 빈도, 현실 전체 분포의 대표성, 원인 정답에 대한 독립 검토를 대신하지 않는다. 이번 데이터의 대부분은 출처를 참고해 만든 통제 데이터라는 분류를 유지한다.
