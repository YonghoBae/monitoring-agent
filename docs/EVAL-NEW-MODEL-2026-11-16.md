# 새 모델 합성 진단 실행 — 2026-11-16

현재 시나리오의 운영 대표성이 검증되지 않았고, 실제 발화 조건과 다른 fixture도 발견됐다. 이번 실행은 운영 정확도나 모델 순위의 근거가 아니다. 먼저 [시나리오 선정 근거 검토](EVAL-REPRESENTATIVENESS-AUDIT-2026-11-16.md)를 읽어야 한다.

## 실행 결과

- 후보·Judge: `qwen3.5:9b-pi32k`, 원격 Ollama 직접 연결. v4, 사례당 1회.
- 전체 38종 원본 결과·도구 기록 저장 완료. fixture 오류 0건, 조사 시간 초과 0건.
- 에이전트 조사 시간 중앙값 44.0초, 최대 80.8초. Judge 호출 시간은 제외한다.
- 도구 호출 0회·관측 trace가 빈 사례 8건.
- 자동 Judge 원본 상태: 미판정 36건, unsupported 2건. **유효한 합격률이 아니다.**
- Judge 보정: 18개 중 6개 일치, 11개 미판정. 독립 Judge·사람 검증 없음.
- 별도 CPU smoke는 90초 한도에 도달했다. 전체 38종 통계에 합산하지 않았다.

## 해석의 한계

데이터셋은 실제 장애의 원본 관측에서 복원한 자료가 아니다. 운영 알람 표현식·메트릭·임계치와 불일치한 사례가 있어 모델의 조사 오류와 평가 설계의 영향을 분리해야 한다. 125개 검증 쿼리 통과는 수치 재생의 내부 일관성을 확인할 뿐이다.

Judge는 최종 답변 대신 숨겨진 정답이나 관측 기록을 인용하거나 JSON을 잘못 출력했다. 검증기는 이를 미판정으로 처리했다. 2개의 unsupported도 보정 실패 상태의 자동 결과이므로 검증된 정답 판정처럼 사용하지 않는다.

아래는 Codex가 원본 답변과 도달한 도구 기록을 대조한 진단 메모다. 독립적인 사람 주석이나 검증된 의미 정확도 점수가 아니다. 도구 미호출인데 호출했다고 주장하는 사례 등은 별도로 재현 가능한 행동 문제로 남긴다. 승인·실행 도구는 이 합성 조사에서 제공하지 않았으므로 실제 승인 정책 숙련도를 검증한 결과도 아니다.

`postgres_autovacuum_bloat`는 실행 시작 후 로그 이름 prefix가 수정됐다. 해당 원본 실행은 수정 전 세계를 사용했고 실제로는 로그 도구를 호출하지 않았다. 수정된 fixture의 계약 검사와 수치 재생은 통과했으나 수정 후 end-to-end 모델 결과로 해석하지 않는다. 대표성 문제 때문에 추가 단일 모델 재실행은 보류했다.

## 실행 설정·보존 자료

- 원본: `build/eval/grounded-20261116-170940/results.jsonl`
- 조건: 같은 폴더의 `conditions.json`, `calibration.jsonl`, `calibration-summary.json`, `model-snapshot.json`
- 모델 digest: `2872f35f2b99c438d19beb6cfaf7002a3150f04c0d850542ca52a554414c233f`
- 모델 기본 설정: num_ctx32768, presence_penalty1.5, top_k20, top_p0.95. 러너 요청은 temperature0, agent maxTokens1536, Judge maxTokens3072.
- 내부 검증: Java 기본 테스트99개, Python44개 통과. 최종 데이터셋38종·수치 검증 쿼리125개 통과.
- 운영 표현식 직접 대조: `build/eval/operational-rule-replay-audit.json`

전체 함수는 `GROUNDED_COMPLETE`까지 도달했지만 Gradle 작업은 마지막 XML 보고서 생성 실패로 exit1이었다. 원본38행과 진행·요약 JSON은 보존됐다. 중간에 잠깐 병행한 단일 재실행이 같은 Gradle 보고서 경로를 사용한 문제가 있어, 이후 evalRun의 binary/XML/HTML 경로를 invocation UUID별로 분리했다. 기존 실행의 XML 성공 여부를 소급해 바꾸지 않는다.

## 사례별 도구 기록 대조

| 사례 | 도구 호출 수 | 진단 메모 |
|---|---:|---|
| cpu_sustained_high | 1 | 추가 메트릭 조회 없이 종료. 실제 CPU 비율 규칙과 fixture의 load5 검증값이 달라 평가 설계도 단위 혼란에 영향을 줌. |
| cpu_transient_spike | 2 | STALE과 CPU 18%는 확인. 합성 기준 시각과 실행 시각을 함께 제시해 시간 해석에 혼동 소지. |
| container_down_bind_error | 2 | 로그 도구 호출 없이 로그를 조회했지만 가져올 수 없었다고 주장. 제공된 bind 오류 근거를 놓침. |
| container_memory_oom | 4 | Java heap OOM은 확인. 일시적 피크라고 단정하고 빈 노드 메트릭을 수집 중단으로 해석. |
| gpu_temperature_high | 3 | 83°C만 확인하고 제공된 GPU 사용률을 추가 조회하지 않음. 실제 운영 임계치와 fixture도 불일치. |
| disk_space_low | 0 | 도구 호출 0회. 현재 상태를 확정하고 추가 조회 권고로 종료. 실제 운영 규칙과 fixture도 불일치. |
| instance_down_network | 2 | 무관한 전체 자원을 조회하고 조사 예고로 종료. 세 exporter의 up=0 비교는 수행하지 않음. |
| http_error_rate_high | 3 | leafy-api 대신 api 로그를 조회. inventory 확인 후 대상을 교정하거나 HTTP 메트릭을 조사하지 않음. |
| postgres_connections_high | 6 | 메트릭 발견 후에도 database 레이블을 사용해 실제 datname과 불일치. 검증값 94도 추론값으로 잘못 설명. |
| alertmanager_reload_failed | 1 | 알람 검증만 했는데 로그·리소스를 확인하고 리소스 원인을 배제했다고 주장. |
| nginx_upstream_502 | 4 | 없는 메트릭과 빈 leafy-api 로그만 조회. 제공된 nginx connection-refused 로그를 놓침. |
| redis_memory_evictions | 5 | 메모리 96%는 계산. eviction 3.44건/초를 3.44건/분으로 잘못 설명하고 정상 동작으로 단정. |
| mysql_slow_queries | 6 | 느린 로그는 확인. EXPLAIN·스키마 없이 full scan과 인덱스 원인을 확정하고 CREATE INDEX를 권고. |
| container_restart_loop | 0 | 도구 호출 0회. 여러 도구로 확인했다고 주장하고 설정 오류 대신 OOM을 제시. |
| host_memory_leak | 2 | RAM 92%는 확인. Jellyfin/worker RSS 추세와 cleanup 로그는 조사하지 않음. |
| disk_io_saturation | 0 | 도구 호출 0회. 조사 계획으로 종료하고 디스크 공간 조회로 I/O wait를 확인할 수 있다고 설명. |
| cert_expiry_soon | 1 | 검증값 604800초를 7일로 해석. certbot 로그 미조회 상태에서 수동 갱신 필요로 단정. |
| prometheus_target_missing | 2 | running inventory에 exporter가 없다는 점만 확인. missing과 up=0 구별 및 NVML 오류 조사는 생략. |
| gpu_memory_full | 2 | VRAM 약 97.1%와 GPU 연산 사용률 45%를 서로 불일치하는 값으로 해석. 모델 로딩 로그 미조회. |
| loki_ingestion_stopped | 4 | 없는 promtail 메트릭과 빈 로그로 수집기 중단을 단정. 제공된 Loki ingestion counter는 미조회. |
| alert_flapping | 3 | 조회하지 않은 CPU 95%·메모리 8.2GiB를 만들어 내고 리소스 고갈과 재시작을 권고. |
| stale_disk_alert_resolved | 0 | 도구 호출 0회. STALE을 검증하지 않고 조사 계획으로 종료. |
| security_ssh_bruteforce | 3 | 호스트 sshd를 Docker 로그로 조회. 인증 실패 메트릭·기존 차단 상태 확인 없이 즉시 IP 차단 권고. |
| network_probe_latency | 3 | 없는 histogram bucket만 조회. 제공된 DNS 3.1초를 조회하지 않고 0초로 추정. 운영 규칙과 fixture도 불일치. |
| postgres_autovacuum_bloat | 1 | 알람 검증만 수행. tuple 비율을 disk bloat 42%로 단정. 실행은 로그 prefix 수정 전 fixture 사용. |
| jellyfin_transcode_cpu | 5 | 잘못된 레이블로 CPU 조회 실패. DCGM 부재를 GPU 부재·비활성으로 단정하고 시간 차이를 수집 지연으로 추정. |
| backup_job_failed | 4 | 디스크 99.8%는 확인. 잘못된 mysql의 빈 로그를 로깅 비활성으로 단정. worker 로그·3일 성공 공백은 미조회. |
| host_oom_killer | 0 | 도구 호출 0회. 현재 RAM을 조회했다고 주장하며 90% 이상으로 단정. fixture의 현재 메모리는 회복 상태. |
| unknown_metric_alert | 3 | UNKNOWN과 원인 미확정은 인식. 추가 정보 요청은 타당하나 소재·관측 불명 단계에서 재시작도 제안. |
| multi_container_down_daemon | 0 | 도구 호출 0회. 검증·inventory·로그 조사를 했다고 주장. 공통 장애 조사 없이 개별 컨테이너 재시작 권고. |
| grafana_datasource_error | 4 | 실제 no-route 로그와 고정 IP는 확인. 실행 중을 정상으로 표현하고 네트워크 격리를 원인으로 확정. |
| nginx_rate_limit_burst | 5 | 로그·요청 rate는 조회. 측정하지 않은 CPU/메모리 정상과 전체 영향 없음을 단정. |
| couchdb_compaction_disk | 5 | 디스크 89%는 확인. CouchDB 지표·compaction 로그 미조회 상태에서 임의 임계치와 일반 로그 정리를 제시. |
| websocket_connection_drop | 4 | 연결 메트릭·nginx 로그·RAG 미조회. 무관한 자원 데이터 부재를 수집 장애로 해석하고 재시작 권고. |
| prometheus_storage_growth | 0 | 도구 호출 0회. 실제 84% 대신 92.5%를 만들고 미호출 메트릭을 조회했다고 주장하며 데이터 삭제 권고. |
| mysql_replication_stopped_binlog | 0 | 도구 호출 0회. 원인 미확정은 표시했으나 제공된 binlog 크기·expiry 조회 없이 계획으로 종료. |
| code_server_unauthorized_access | 1 | 알람 검증만 수행. 실제 스캐너 로그·401 메트릭 미조회 상태에서 인증 서버·토큰 원인을 제시. |
| time_drift_ntp | 1 | 무관한 전체 자원만 조회. offset·sync 미조회 상태에서 NTP 원인을 추정하고 서비스 재시작 권고. |
