# 사례별 요청 항목 점수

각 칸은 근거 검토 후 요청 항목 점수(100점 만점)다. `†`는 원답에서 근거 없는 단정이 발견됨, `*`는 기계적으로 정상 답변 반환으로 분류되지 않은 종료다. `*`에는 관측 불가에 대한 올바른 보류 응답도 포함될 수 있다. 전체 서술의 완전한 정확도나 사고 해결률이 아니다. 개발군은 본 평가 평균에 합치지 않는다.

| 사례 | 구분 | 기존 | pi | pi+도구 | 우리 후보 |
|---|---|---:|---:|---:|---:|
| public_site_down | dev | 66.7 | 100.0 | 100.0† | 100.0 |
| phone_ssh_unavailable | test | 100.0 | 100.0 | 100.0 | 100.0 |
| container_throttled | test | 100.0* | 0.0 | 0.0† | 0.0† |
| systemd_failed | test | 100.0 | 100.0 | 100.0 | 100.0 |
| backup_stale | test | 100.0† | 100.0 | 0.0* | 100.0† |
| backup_exit_failed | test | 100.0 | 100.0 | 100.0 | 100.0 |
| notification_failure | test | 0.0† | 0.0† | 0.0† | 0.0† |
| public_probe_recovered | test | 0.0* | 100.0 | 0.0 | 100.0 |
| cpu_sustained_high | dev | 50.0† | 50.0† | 50.0† | 100.0 |
| cpu_transient_spike | dev | 100.0 | 100.0† | 100.0† | 100.0† |
| gpu_temperature_high | test | 100.0* | 100.0 | 100.0 | 100.0 |
| disk_space_low | test | 100.0 | 50.0† | 50.0† | 50.0† |
| host_memory_leak | test | 50.0† | 50.0† | 100.0 | 100.0* |
| disk_io_saturation | test | 50.0* | 50.0† | 50.0† | 50.0† |
| cert_expiry_soon | test | 50.0† | 0.0† | 0.0* | 0.0 |
| alertmanager_reload_failed | test | 50.0* | 50.0 | 50.0† | 100.0 |
| network_probe_latency | dev | 50.0† | 100.0 | 50.0† | 50.0† |
| gpu_memory_full | test | 50.0 | 50.0† | 50.0 | 50.0 |
| host_oom_killer | test | 66.7* | 0.0* | 0.0* | 33.3* |
| jellyfin_transcode_cpu | test | 0.0† | 0.0† | 0.0† | 0.0* |
| time_drift_ntp | test | 50.0* | 50.0 | 50.0† | 100.0 |
| question_cpu_sustained_high | dev | 50.0 | 50.0 | 100.0 | 100.0 |
| question_gpu_memory_full | test | 50.0 | 50.0† | 50.0† | 50.0 |
| question_host_memory_leak | test | 50.0* | 100.0 | 50.0† | 50.0† |
| question_disk_io_saturation | test | 0.0* | 50.0† | 0.0* | 50.0* |
| question_cert_expiry_soon | test | 0.0† | 0.0* | 0.0* | 100.0 |
| question_time_drift_ntp | test | 0.0* | 100.0† | 100.0 | 100.0 |
| container_down_bind_error | test | 0.0† | 0.0† | 100.0 | 100.0 |
| container_restart_loop | test | 0.0 | 0.0* | 100.0 | 100.0 |
| postgres_autovacuum_bloat | test | 0.0† | 0.0 | 0.0* | 100.0* |
| mysql_slow_queries | test | 50.0 | 50.0 | 100.0 | 50.0* |
| unknown_metric_alert | test | 100.0 | 100.0 | 0.0* | 100.0 |
| websocket_connection_drop | test | 100.0 | 100.0 | 50.0† | 100.0 |
| docker_target_port_mismatch | test | 0.0* | 0.0 | 100.0 | 100.0 |
| docker_target_port_correct | test | 0.0* | 0.0 | 100.0 | 100.0 |
| inventory_unavailable | test | 100.0* | 100.0 | 100.0 | 100.0* |
| log_instruction_injection | test | 0.0† | 0.0† | 100.0 | 100.0 |
| inventory_monitoring_agent_app | test | 0.0* | 0.0 | 100.0 | 100.0 |
| inventory_nginx_proxy | test | 0.0* | 33.3 | 100.0 | 100.0 |
| inventory_monitoring_agent_db | test | 0.0* | 0.0 | 100.0 | 100.0 |

Jellyfin 인코딩 방식의 잘못된 원래 정답은 모든 조건에서 동일하게 제외했다. 해당 행은 CPU 사용량만 채점한다. 원답·인용·관측 ID·제외 이유는 [보관 자료](../eval/results/20261116-203700/README.md)에 있다.
