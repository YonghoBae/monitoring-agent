# 현재 평가 시나리오가 홈서버 운영을 대표하는가

2026-11-16 운영 Prometheus의 `/api/v1/rules?type=alert`, 메트릭 이름 목록, 최근 30일 `alert_event` 집계를 읽기 전용으로 대조했다.

**현재 38종을 홈서버 운영의 대표 평가셋으로 간주할 근거는 부족하다.** 현재 자료로 검증한 것은 합성 환경의 내부 일관성과 일부 도구 행동이다. 실제 업무 빈도·중요도·운영 관측 가능성·정답 검증을 연결한 평가셋 선정 근거가 없다.

## 확인된 사실

- 데이터 출처는 `kind: synthetic`, `measurement_status: not measured`다. 모든 수치가 실제 장애 실측에서 나온 것은 아니라는 설명도 명시돼 있다.
- 운영 Prometheus가 로드한 알람 규칙은 58개다. 평가 38개 사례의 알람 이름은 33종이며, 이름이 정확히 일치하는 것은 `HostHighCpuLoad`를 사용하는 2개 사례뿐이다. **이는 이름 정합성 검사이며 의미적 커버리지 수치가 아니다.** 별칭으로 같은 업무를 평가할 수도 있지만, 그 연결이 문서화돼 있지 않다.
- 평가에 사용한 메트릭 이름은 54종이다. 운영에서 조회한 메트릭 이름 목록에서 29종을 찾았고 25종은 찾지 못했다. 이 결과만으로 메트릭이 영구적으로 수집 불가능하다고 단정할 수는 없다. 다만 현재 관측 환경과의 정합성은 입증되지 않았다.
- 최근 30일 알람 저장 행은 명시적인 `SyntheticDrillHttpUnavailable` 1행을 제외하면 158행이다. 그중 `PublicSiteSlow` 95행, `PublicSiteDown` 34행이다. **저장 행은 중복 알림을 포함할 수 있으므로 독립 장애 횟수나 장애 확률로 해석하지 않는다.**
- 위 158행 중 `starts_at` 누락은 0행, `resolved=true`는 156행, `resolution_record_id`가 연결된 행은 0행이다. resolved 상태는 해소 여부이며, 원인이 검증됐다는 뜻은 아니다.
- 기존 연구 비교 문서에도 외부 연구가 이 프로젝트의 데이터셋을 검증한 것은 아니라고 명시돼 있다. 평가 방법론 참고와 프로젝트 시나리오 선정의 실증 근거는 별개다.

## 운영 표현식으로 직접 재검증한 사례

운영에서 실제 로드된 표현식을 합성 세계의 격리 Prometheus에 그대로 질의했다. 아래는 평가 시각의 표현식 결과이며 `for` 기간을 포함한 알람 상태 머신 재생은 아니다.

| 사례 | fixture의 고정 검증값 | 실제 운영 표현식 결과 |
|---|---|---|
| cpu_sustained_high | CONFIRMED, 6.4 | 0.92 (CPU 비율). 조건은 만족하지만 반환값의 의미가 다름 |
| gpu_temperature_high | CONFIRMED, 83 | 빈 결과. 현재 온도는 >85 조건 미충족 |
| disk_space_low | CONFIRMED, 0.87 | 빈 결과. 가용13%는 <10% 미충족이며 readonly 입력도 누락 |
| network_probe_latency | CONFIRMED, 4.2 | 빈 결과. >5초 미충족이며 실제 job/probe_success 입력도 부족 |

원본 질의·결과는 `build/eval/operational-rule-replay-audit.json`에 저장했다. 이 불일치는 현재 `verify_alert` 상태가 실제 규칙 평가에서 계산되지 않고 별도 mock으로 고정되기 때문에 가능하다.

## 실제 이력과 주요 누락

| 최근 30일 알람 이름 | 저장 행 |
|---|---:|
| PublicSiteSlow | 95 |
| PublicSiteDown | 34 |
| ContainerKilled | 13 |
| PhoneSSHUnavailable | 7 |
| HostSystemdServiceCrashed | 6 |
| HostDiskMayFillIn24Hours | 1 |
| HostContextSwitchingHigh | 1 |
| ContainerHighThrottleRate | 1 |

현재 v3에는 이 중 일부와 유사한 합성 과제는 있지만 실제 규칙·레이블·관측 구간·발생 이력과 연결한 대표 사례가 없다. 특히 공개 사이트 다운/지연, 휴대폰 SSH, systemd 실패, 컨테이너 throttling 등의 실제 업무가 평가에서 명시적으로 다뤄지는지 재검토해야 한다. 반면 MySQL·Redis·CouchDB 진단 등은 보편적인 관제 과제로는 유용할 수 있어도 현재 홈서버에서의 우선순위 근거가 제시돼 있지 않다.

알람 빈도가 높다는 사실만으로 업무 중요도나 실제 장애 빈도가 높다고 판단하지 않는다. 반복 노이즈일 수도 있고, 이력 당시의 규칙·라우팅 설정이 현재 설정과 다를 수도 있다. 사건 중복 제거와 당시 규칙 버전, 실제 영향 확인이 선행돼야 한다.

## 38개 사례와 운영 규칙의 연결 후보

아래는 표현·메트릭을 읽고 작성한 **연결 후보**다. 검증된 규칙 커버리지나 실제 발생 사례 연결표는 아니다. 이름이 비슷해도 발화 조건·데이터가 다르면 같은 과제라고 확정하지 않았다.

| 사례 | 운영 규칙 연결 후보 | 확인한 차이·한계 |
|---|---|---|
| cpu_sustained_high | HostHighCpuLoad | 실제 규칙은 CPU 비율 >0.8, 10분. fixture 검증값6.4는 load5이며 실제 알람 표현식 값과 다름 |
| cpu_transient_spike | HostHighCpuLoad | 회복/ST​ALE 행동 진단에 사용 가능. 실제 발생·해소 이벤트 연결은 없음 |
| container_down_bind_error | ContainerKilled / ContainerAbsent | 컨테이너 발견·last-seen 규칙과 연결 검증 필요. 현재 알람 이름·레이블은 다름 |
| container_memory_oom | ContainerHighMemoryUsage | 실제 working_set 기반 메트릭과 fixture usage_bytes가 다름. Java heap OOM은 ContainerOOMKilled의 cgroup OOM 증거가 아님 |
| gpu_temperature_high | GPUHighTemperature | 실제 >85°C, fixture83°C를 CONFIRMED로 고정. 현재값으로 실제 온도 규칙은 발화하지 않음 |
| disk_space_low | HostOutOfDiskSpace / HostDiskMayFillIn24Hours | fixture 가용13%는 실제 <10% 조건 미충족. readonly 메트릭 등 실제 표현식 입력도 부족 |
| instance_down_network | 직접 대응 규칙 확인 못 함 | exporter 공통 장애라는 가설 과제. 운영 알람 발생 조건 연결 필요 |
| http_error_rate_high | 직접 대응 규칙 확인 못 함 | HTTP5xx 메트릭·알람 및 실제 서비스 대상 근거 필요 |
| postgres_connections_high | 직접 대응 규칙 확인 못 함 | exporter 메트릭과 실제 연결 고갈 사건 근거 없음 |
| alertmanager_reload_failed | AlertmanagerConfigStale | reload_successful==0이라는 표현식은 연결 가능. 이름·payload 정합성 필요 |
| nginx_upstream_502 | 직접 대응 규칙 확인 못 함 | 실제 nginx 관측·알람 구성 근거 필요 |
| redis_memory_evictions | 직접 대응 규칙 확인 못 함 | 현재 Redis 관측과 업무 중요도 근거 필요 |
| mysql_slow_queries | 직접 대응 규칙 확인 못 함 | 현재 MySQL 관측·스키마·진단 이력 근거 필요 |
| container_restart_loop | ContainerRestarting | 실제는 changes(container_start_time_seconds[15m])>3. fixture는 별도 container_restart_count 사용 |
| host_memory_leak | HostHighMemoryUsage / HostOutOfMemory | 사용률92%는 조건에 맞출 수 있음. 실제 누수 사건·프로파일 정답은 없음 |
| disk_io_saturation | HostDiskIoUtilizationHigh | busy97%는 실제 >80%와 연결 가능. 백업이 원인이라는 실측 연결은 없음 |
| cert_expiry_soon | PublicCertExpiringSoon | 7일은 실제 <14일과 연결 가능. 실제 발급/갱신 실패 로그와의 연결은 없음 |
| prometheus_target_missing | GPUDcgmExporterDown | 실제는 up==0, fixture는 해당 시계열 부재. 부재는 up==0을 만족하지 않아 서로 다름 |
| gpu_memory_full | GPUHighMemoryUsage | 실제 식은 FB_USED/FB_TOTAL. fixture는 FB_USED+FB_FREE로 계산하며 FB_TOTAL 제공 안 함 |
| loki_ingestion_stopped | 직접 대응 규칙 확인 못 함 | 실제 ingestion 관측과 경보 구성 연결 필요 |
| alert_flapping | 직접 대응 규칙 확인 못 함 | up 진동은 프로세스 재시작과 다름. 별도 경계 상황 진단으로는 유용 |
| stale_disk_alert_resolved | 디스크 규칙의 해소 사례 | 가용41%는 회복 상태와 부합. 실제 firing→resolved 전이 연결 필요 |
| security_ssh_bruteforce | 직접 대응 규칙 확인 못 함 | sshd 공격 관측·실제 방어 상태 근거 필요. PhoneSSHUnavailable과는 다른 과제 |
| network_probe_latency | PublicSiteSlow | 실제 >5초와 probe_success=1 및 job 조건 필요. fixture4.2초는 실제 임계치 미충족 |
| postgres_autovacuum_bloat | 직접 대응 규칙 확인 못 함 | 운영 vacuum 관측·락 이력 근거 필요 |
| jellyfin_transcode_cpu | ContainerHighCpuUtilization / HostHighCpuLoad | 3.8/4코어는 해당 사용률 규칙과 연결 가능. 실제 transcode 사건 연결 필요 |
| backup_job_failed | BackupFailed / BackupStale | 실제 db_backup_* 메트릭과 fixture backup_last_success_timestamp 이름이 다름 |
| host_oom_killer | HostOomKillDetected | counter 증가를 실제 delta[30m] 규칙에 맞출 수 있음. 실제 victim 정답은 확보되지 않음 |
| unknown_metric_alert | 직접 대응 규칙 확인 못 함 | 불확실성 인정 테스트. 실제 발생 분포의 대표 사례와 분리해야 함 |
| multi_container_down_daemon | ContainerKilled / ContainerAbsent | 실제 compose 레이블 필터 등 조건 재현 필요. 공통 Docker 원인 정답은 합성 가설 |
| grafana_datasource_error | 직접 대응 규칙 확인 못 함 | 실제 datasource 장애·로그 정답 근거 필요 |
| nginx_rate_limit_burst | 직접 대응 규칙 확인 못 함 | 실제 rate-limit 정책·client 영향 근거 필요 |
| couchdb_compaction_disk | 디스크 규칙과 간접 관련 | 실제 CouchDB 지표·compaction 사건 근거 필요 |
| websocket_connection_drop | 직접 대응 규칙 확인 못 함 | 실제 접속 변화·reload 사건 정렬 근거 필요 |
| prometheus_storage_growth | 디스크 규칙과 간접 관련 | URI별1.2M series는 명시적 합성 진단 메트릭. 실제 exporter 기본 증거가 아님 |
| mysql_replication_stopped_binlog | 직접 대응 규칙 확인 못 함 | 실제 replica 상태·binlog·복구 요구사항 근거 없음 |
| code_server_unauthorized_access | 직접 대응 규칙 확인 못 함 | 실제 외부 노출 경로·인증 로그 근거 필요 |
| time_drift_ntp | HostClockSkew / HostClockNotSynchronising | offset은 skew 규칙 연결 가능. 실제 sync 규칙의 maxerror 메트릭은 fixture에 없음 |

## 적절한 용도와 다음 선정 기준

현재 38종은 **합성 상황에서 관측을 읽고 도구를 선택하는 행동 진단**에 사용할 수 있다. 실제 운영 정확도, 실제 장애 분포 커버리지, 원인 진단 성공률의 근거로는 부족하다. 숫자나 로그를 합성하는 것 자체가 문제는 아니다. 운영 규칙·업무·관측 가능성과 연결하지 않은 채 대표 성능으로 해석하는 것이 문제다.

운영 평가용 사례에는 다음 근거를 붙여야 한다.

1. **업무 출처:** 실제 알람 규칙 또는 실제 운영 질문. 알람·대화 조사를 별도 업무로 구분한다.
2. **사건 단위:** fingerprint에 해당하는 레이블·시작 시각·해소 시각으로 중복 알림을 묶는다. 알림 행 수를 장애 횟수로 사용하지 않는다.
3. **당시 관측:** 그 시점에 에이전트가 조회할 수 있었던 메트릭·로그·inventory·도구 오류. 사후 지식이나 미래 관측을 정답 근거로 섞지 않는다.
4. **검증된 정답 범위:** 알람 해소, 확인된 사실, 운영자가 확인한 원인과 조치. 원인 미확인 사건은 ‘원인 미확정’이 올바른 답일 수 있다.
5. **재현 가능성:** 실제 표현식·레이블·단위·for 기간을 재생해 발생/해소 상태를 계산한다. 현재처럼 verify 상태를 독립적으로 고정하지 않는다.
6. **추가 경계 사례:** 실제 빈도가 낮아도 중요한 OOM·백업 실패·관측 불가·오래된 알람·권한 문제는 규칙에 맞춘 합성 사례로 보강하되 실측 사례와 출처를 구별한다.
7. **검증 분리:** 사건별로 개발/평가 데이터를 나누고, 정답과 판정기를 독립적으로 검토한다. 같은 사건의 알림이나 수치 변형을 양쪽에 섞지 않는다.

최근 이력에 연결된 해결 기록이 없으므로 기존 알람 행만 복사해 근본 원인 정답을 만들면 안 된다. 과거 관측을 복구할 수 없는 사건은 데이터 한계를 명시하거나, 실제 규칙에 근거한 통제된 합성 재현으로 전환해야 한다.

현재 모델 실행 결과에는 이 제한을 적용한다. 근거 없는 도구 사용 주장 등 진단 사례는 보존하지만, 합격률이나 운영 정확도·모델 순위를 주장하지 않는다.
