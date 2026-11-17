# 2026-11-16 평가 데이터셋 전수 검토

이 문서의 검증은 합성 fixture의 내부 일관성에 관한 것이다. **홈서버 운영 대표성은 입증되지 않았다.** 실제 운영 규칙·최근 알람 이력과 대조한 [선정 근거 검토](EVAL-REPRESENTATIVENESS-AUDIT-2026-11-16.md)를 함께 읽어야 한다. 실제 임계치와 다른데 CONFIRMED로 고정된 사례도 발견돼, 현재 결과를 운영 정확도로 해석할 수 없다.

검토 범위는 저장소의 평가 데이터 파일 5개다. v1의 10개 시나리오는 v2의 부분집합이며 원본 필드가 동일하다. v3는 v2의 38개 ID·알람·플레이북을 보존한다. 버전별 건수를 합산해 독립 사례 수로 표시하면 안 된다.

| 파일 | 내용 | 판단 |
|---|---|---|
| eval-scenarios.json | 5개 고정 응답·도구 호출·Judge 응답 | 코드 회귀 검사용. 실제 모델 성능 측정 자료가 아님 |
| eval-dataset-v1.yml | 10개 상황·기대 행동 | v2에 그대로 포함된 과거 정답 기준 |
| eval-dataset-v2.yml | 38개 설명형 관측 요약 | 과거 비교 보존용. 일부 정답이 관측 이상의 인과 단정을 요구함 |
| eval-dataset-v3.yml | 38개 수치 시계열·로그·RAG·의미 정답 | 이번 실행에 사용. 격리 Prometheus에서 검증 쿼리 125개 통과 |
| eval-judge-calibration-v1.yml | 8개 그룹, 답변 후보 18개 | 작성자 주석이며 사람 검증 전. Judge 진단에 사용 |

## 발견하고 수정한 문제

1. **재생 불가능한 디스크 이력:** `disk_space_low`는 7일 데이터를 제공하지만 재생기는 최대 5일만 허용했다. 허용 범위를 7일로 맞췄다. 샘플 수 상한은 유지한다. 전체 시나리오 렌더링 회귀 검사도 추가했다.
2. **STALE 정답 충돌:** `cpu_transient_spike`는 즉시 종료를 허용하는 정책과 달리 CPU/load 재조회 사실을 필수로 요구했다. STALE 확인과 복구 보고만으로 충족하도록 수정하고 수치 조회는 선택 사항으로 명시했다.
3. **메모리 검증값 충돌:** `host_memory_leak`의 총 메모리 16 GB, 가용 2.4 GB는 사용률 85%인데 알람 검증값은 92%였다. 마지막 가용값을 1.28 GB로 맞춰 현재 92% 조건을 일치시켰다.
4. **불가능한 네트워크 시간:** `network_probe_latency` 과거 DNS 시간이 3.1초로 전체 probe 0.4초를 초과했다. DNS 이력을 0.1 → 1.5 → 3.1초로 수정했다. 마지막 현재값은 동일하다.
5. **평가 코드 컴파일 실패:** 기존 Oracle 테스트는 최종 답변까지 받는 검증 함수를 호출했으나 구현에는 인자가 세 개인 함수만 있었다. 최종 답변 인용 검증을 구현하고 실제 러너에도 연결했다. Judge가 숨겨진 정답 문장을 실제 답변에 귀속하면 미판정한다. 이 변경은 과거 Judge 결과와 채점 조건이 다르다.

6. **조회할 수 없는 로그 정답:** `postgres_autovacuum_bloat`는 컨테이너 이름이 `monitoring-agent-db`인데 로그 본문에는 `postgres`만 포함되어 실제 도구의 이름 필터를 통과하지 못했다. 본문 prefix를 컨테이너 이름으로 맞추고, Docker 비어 있지 않은 로그가 실제 시간 범위·이름 필터를 통과하는지 회귀 검사에 추가했다. 전체 실행 시작 후 발견한 수정이므로 기존 실행은 수정 전 fixture로 표시한다. 해당 실행은 로그 도구를 호출하지 않았으므로 조사 누락 진단은 가능하지만 수정 후 end-to-end 성능 검증 자료로 사용하지 않는다. 운영 대표성 문제가 확인돼 추가 단일 재실행은 보류했다.

과거 v1/v2 데이터와 과거 실행 결과는 수정하지 않았다.

## 38개 사례 검토표

모든 행에서 수치·레이블·로그 출처·정답 근거를 대조하고 실제 Prometheus 검증 쿼리를 실행했다. 쿼리 통과는 정답의 의미까지 자동 검증한 결과가 아니다.

| 시나리오 | 검토한 핵심 기준 |
|---|---|
| cpu_sustained_high | 4코어 CPU 92%, load5 6.4. 배치 작업은 기여 요인 가설 |
| cpu_transient_spike | STALE 즉시 종료 허용. 추가 조회 시 CPU 18%, load 0.9 |
| container_down_bind_error | down/오래된 last-seen과 bind 오류. 포트 점유자는 미확인 |
| container_memory_oom | 1.86/2 GB=93%, Java heap OOM과 kernel kill 구별 |
| gpu_temperature_high | 83°C, GPU 97%. VRAM은 MiB 단위 |
| disk_space_low | 7일 가용 41→13 GB, 총 100 GB. 무조건 삭제 금지 |
| instance_down_network | 세 exporter down은 공통 장애 단서. 특정 네트워크 원인은 미확인 |
| http_error_rate_high | 최근 5분 5xx 8%, pool timeout. DB 근본 원인 단정 금지 |
| postgres_connections_high | 총 94/100, DB idle 82와 앱 pool idle 0은 다른 범위 |
| alertmanager_reload_failed | reload=0, YAML line42. 정확한 수정 내용은 미확인 |
| nginx_upstream_502 | 502 45회/분, scrape up과 application readiness 구별 |
| redis_memory_evictions | 메모리 96%, 시간당 eviction 12400. 삭제 안전성은 미확인 |
| mysql_slow_queries | 시간당 38 증가, 12.4초 쿼리. 인덱스 누락은 가설 |
| container_restart_loop | 10분간 6회 증가, MYSQL_HOST 미설정. 재시작 반복 부적절 |
| host_memory_leak | 현재 사용률 92% 일치. Jellyfin RSS 증가와 leak 확정 구별 |
| disk_io_saturation | busy 97%, 쓰기 180 MB/s. 지연·큐 길이를 꾸미지 않음 |
| cert_expiry_soon | 평가 시각 기준 7일 남음. port80 소유자는 미확인 |
| prometheus_target_missing | dcgm series 누락과 up=0 구별. NVML mismatch 로그 |
| gpu_memory_full | 23859.2/24576 MiB≈97.08%. 낮은 utilization이 정상 서비스 증거는 아님 |
| loki_ingestion_stopped | scrape up과 최근 30분 ingestion 정지 구별 |
| alert_flapping | up 교대와 현재 1. 분 단위 데이터로 40초 outage 단정 금지 |
| stale_disk_alert_resolved | STALE 즉시 종료. 선택적 조회 시 38 GB, 약 41% 가용 |
| security_ssh_bruteforce | 시간당 실패 312회. host 로그를 읽지 못하면 차단 여부 등 미확인 |
| network_probe_latency | 현재 전체 4.2초 중 DNS 3.1초. 과거 DNS≤전체 조건 수정 |
| postgres_autovacuum_bloat | dead 182K/live430K, vacuum 26시간 전. disk bloat 비율과 구별 |
| jellyfin_transcode_cpu | 컨테이너 3.8 CPU cores, 호스트 4코어. 소프트웨어 transcode 로그 |
| backup_job_failed | 3일 성공 공백, 120 MB/60 GB 가용. dump 성공과 archive 실패 구별 |
| host_oom_killer | kill counter +1, 메모리 회복. 정확한 kernel victim은 미확인 |
| unknown_metric_alert | queue 관측 부재를 인정. 무관한 load/up으로 queue 상태 추정 금지 |
| multi_container_down_daemon | 6개 Docker 대상 down, 외부 관측 정상. 개별 재시작보다 공통 원인 조사 |
| grafana_datasource_error | 두 scrape up, 고정 IP 경로 오류. datasource 연결과 프로세스 생존 구별 |
| nginx_rate_limit_burst | 10.0.0.42에 503 집중. 다른 한 client 정상으로 전체 사용자 무영향 단정 금지 |
| couchdb_compaction_disk | disk/data 차이 39 GB는 추정이며 회수 보장 아님 |
| websocket_connection_drop | 41→0→39, 67초 후 부분 복구. 전원 재연결로 채점하면 안 됨 |
| prometheus_storage_growth | head 180K→1.4M. URI 귀속은 명시적 합성 진단 메트릭의 근거 필요 |
| mysql_replication_stopped_binlog | binlog 31 GB, expiry 0. replica 상태와 삭제 안전성 미확인 |
| code_server_unauthorized_access | 401 시간당220, 14 sources. scan 정황과 침해 확정 구별 |
| time_drift_ntp | offset 0.83초, sync0 3일. timeout만으로 firewall 차단 단정 금지 |

## 과거 데이터의 제한

v2의 `time_drift_ntp`는 UDP123 차단 원인을 찾도록 요구하지만 v3에서 관측 가능한 근거는 offset/sync 및 제한된 로그다. `host_oom_killer`는 kernel victim 특정, `nginx_rate_limit_burst`는 실제 사용자 무영향, `websocket_connection_drop`는 회복 확인 등을 요구한다. 이 기준들은 근거의 범위를 넘어서는 해석을 보상할 수 있어 새 모델의 주 평가에는 사용하지 않았다.

고정 응답 JSON의 S1은 프로세스와 컨테이너의 연결을 추정하고, S2는 과거 메모리 설정이 되돌아갔다고 단정한다. S3는 관측되지 않은 thermal threshold를 제시하며, S4는 과거 RAG의 좀비 원인을 현재 원인으로 확정하고 restart/kill을 정답처럼 다룬다. S5는 VRAM을 직접 관측하지 않은 가설을 포함한다. 따라서 이 파일의 고정 Judge 점수를 모델 정확도로 인용하면 안 된다.

## 검증과 재실행

- Java 기본 회귀 전체 99개 통과. Oracle 14개, 수치 도구 연동 1개, 기존 데이터 회귀 3개를 포함한다.
- v3 Python 계약 검사: 전체 렌더링과 추가 수치 정합성 검사 포함 6개 통과.
- Python 평가·라우터 회귀 전체 44개 통과. 수치 재생기 11개, 구형 설명형 fixture 13개를 포함한다.
- 전체 38개 세계, 검증 쿼리 125개 통과. 출력: `build/eval/dataset-audit.json` (원본 SHA256, 실행 시각 포함).

```bash
rtk proxy python3 scripts/audit_eval_dataset.py
rtk proxy env RUN_NUMERIC_FIXTURE_TESTS=1 python3 -m unittest discover -s scripts/tests -p test_numeric_fixture.py
rtk proxy python3 -m unittest discover -s scripts/tests -p test_eval_dataset_v3.py
```

수치 재생기의 이미지는 기존 로컬 `prom/prometheus:v2.53.0`을 사용한다. 운영 Prometheus에는 데이터를 적재하지 않는다.

## 새 모델 평가 조건과 해석

후보: `qwen3.5:9b-pi32k`, 직접 Ollama 연결, context32768, v4 arm, 시나리오당 1회. 기존 라우터는 모델을 고정하므로 이번 실행은 원격 Ollama를 직접 호출한다. 운영 라우터 설정은 변경하지 않았다.

첫 CPU smoke는 90초 조사 한도에 도달했다. CPU92% 관측은 있었으나 원인 조사를 완료하지 못했다. 기존 `qwen3:8b` Judge 보정은 18개 중10개 일치, 미판정7개, 잘못된 합격1개였다. 해당 채점으로 모델 개선을 주장할 수 없다.

전체 실행은 긴 입력을 처리하는 후보 모델을 Judge로도 사용한다. 동일 모델 자기 선호 편향이 있고 사람 검증이 없으므로 탐색 결과다. 보정 실패·미판정은 별도로 보고하고 유효한 합격률/모델 순위를 주장하지 않는다. 과거 설명형 mock 실행과 이번 수치형 실행을 직접적인 개선율로 비교하면 안 된다.
