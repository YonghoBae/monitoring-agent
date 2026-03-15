package io.ohgnoy.monitoring.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.repository.AlertEventRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.*;

@Service
public class AlertContextCollector {

    private static final Logger log = LoggerFactory.getLogger(AlertContextCollector.class);

    private final PrometheusQueryService prometheusQuery;
    private final LokiQueryService lokiQuery;
    private final AlertEventRepository alertEventRepository;
    private final ObjectMapper objectMapper;

    public AlertContextCollector(PrometheusQueryService prometheusQuery,
                                 LokiQueryService lokiQuery,
                                 AlertEventRepository alertEventRepository,
                                 ObjectMapper objectMapper) {
        this.prometheusQuery = prometheusQuery;
        this.lokiQuery = lokiQuery;
        this.alertEventRepository = alertEventRepository;
        this.objectMapper = objectMapper;
    }

    public AlertContext collect(AlertEvent alert) {
        Map<String, String> labels = parseLabels(alert.getLabelsJson());

        // 알람 발생 30분 전부터 현재까지 조회
        Instant queryStart = alert.getStartsAt() != null
                ? alert.getStartsAt().atZone(ZoneId.systemDefault()).toInstant().minus(30, ChronoUnit.MINUTES)
                : Instant.now().minus(1, ChronoUnit.HOURS);
        Instant now = Instant.now();

        List<String> metrics = collectMetrics(alert.getAlertName(), labels, queryStart, now);
        List<String> logs = collectLogs(alert.getAlertName(), labels, queryStart, now);
        List<String> concurrent = collectConcurrentAlerts(alert.getId());

        return new AlertContext(metrics, logs, concurrent);
    }

    private List<String> collectMetrics(String alertName, Map<String, String> labels,
                                        Instant start, Instant end) {
        if (alertName == null) return List.of();

        List<String> results = new ArrayList<>();
        buildMetricQueries(alertName, labels).forEach((label, expr) -> {
            String summary = prometheusQuery.querySummary(label, expr, start, end);
            if (summary != null) results.add(summary);
        });
        return results;
    }

    // LinkedHashMap으로 쿼리 순서 유지
    private Map<String, String> buildMetricQueries(String alertName, Map<String, String> labels) {
        String name = labels.getOrDefault("name", "");
        String instance = labels.getOrDefault("instance", "");
        String gpu = labels.getOrDefault("gpu", "");
        String clientName = labels.getOrDefault("client_name", "");

        return switch (alertName) {
            case "ContainerHighMemoryUsage", "ContainerOOMKilled", "ContainerRestarting" -> {
                if (name.isBlank()) yield Map.of();
                Map<String, String> m = new LinkedHashMap<>();
                m.put("메모리 사용량", "container_memory_usage_bytes{name=\"" + name + "\"}");
                m.put("메모리 제한", "container_spec_memory_limit_bytes{name=\"" + name + "\"}");
                m.put("재시작 횟수(15m)", "increase(container_restarts_total{name=\"" + name + "\"}[15m])");
                yield m;
            }
            case "ContainerDown" -> {
                if (name.isBlank()) yield Map.of();
                Map<String, String> m = new LinkedHashMap<>();
                m.put("마지막 확인", "container_last_seen{name=\"" + name + "\"}");
                yield m;
            }
            case "GPUHighTemperature" -> {
                if (gpu.isBlank()) yield Map.of();
                Map<String, String> m = new LinkedHashMap<>();
                m.put("GPU 온도", "DCGM_FI_DEV_GPU_TEMP{gpu=\"" + gpu + "\"}");
                m.put("GPU 사용률", "DCGM_FI_DEV_GPU_UTIL{gpu=\"" + gpu + "\"}");
                yield m;
            }
            case "GPUHighMemoryUsage" -> {
                if (gpu.isBlank()) yield Map.of();
                Map<String, String> m = new LinkedHashMap<>();
                m.put("GPU 메모리 사용(MiB)", "DCGM_FI_DEV_FB_USED{gpu=\"" + gpu + "\"}");
                m.put("GPU 메모리 전체(MiB)", "DCGM_FI_DEV_FB_TOTAL{gpu=\"" + gpu + "\"}");
                yield m;
            }
            case "GPUUtilizationStuckHigh", "GPUDcgmExporterDown" -> {
                Map<String, String> m = new LinkedHashMap<>();
                String gpuFilter = gpu.isBlank() ? "" : "{gpu=\"" + gpu + "\"}";
                m.put("GPU 사용률", "DCGM_FI_DEV_GPU_UTIL" + gpuFilter);
                yield m;
            }
            case "HostHighCpuLoad" -> {
                Map<String, String> m = new LinkedHashMap<>();
                String instFilter = instance.isBlank() ? "" : "{instance=\"" + instance + "\"}";
                String instLabel = instance.isBlank() ? "" : ",instance=\"" + instance + "\"";
                m.put("CPU 사용률(%)", "(100 - (avg by (instance) (irate(node_cpu_seconds_total{mode=\"idle\"" + instLabel + "}[5m])) * 100))");
                m.put("Load Average(1m)", "node_load1" + instFilter);
                yield m;
            }
            case "HostHighMemoryUsage" -> {
                Map<String, String> m = new LinkedHashMap<>();
                String instFilter = instance.isBlank() ? "" : "{instance=\"" + instance + "\"}";
                m.put("여유 메모리", "node_memory_MemAvailable_bytes" + instFilter);
                m.put("메모리 사용률", "(node_memory_MemTotal_bytes" + instFilter
                        + " - node_memory_MemAvailable_bytes" + instFilter
                        + ") / node_memory_MemTotal_bytes" + instFilter);
                yield m;
            }
            case "ApolloGameHighFrameLatency", "ApolloGameInputBacklog", "ApolloGeneralTypingLag" -> {
                Map<String, String> m = new LinkedHashMap<>();
                String clFilter = clientName.isBlank() ? "" : "{client_name=\"" + clientName + "\"}";
                m.put("프레임 지연 비율", "apollo:frame_latency_ratio:avg_1m" + clFilter);
                m.put("입력 큐 깊이", "apollo:input_queue_depth:avg_1m" + clFilter);
                m.put("입력 처리 지연(ms)", "apollo:input_processing_latency:avg_1m" + clFilter);
                yield m;
            }
            default -> Map.of();
        };
    }

    private List<String> collectLogs(String alertName, Map<String, String> labels,
                                     Instant start, Instant end) {
        if (alertName == null) return List.of();
        String name = labels.getOrDefault("name", "");

        Optional<String> query = switch (alertName) {
            case "ContainerHighMemoryUsage", "ContainerOOMKilled",
                 "ContainerRestarting", "ContainerDown" ->
                    name.isBlank() ? Optional.empty()
                            : Optional.of("{job=\"docker\"} |= \"" + name + "\"");
            case "ApolloGameHighFrameLatency", "ApolloGameInputBacklog", "ApolloGeneralTypingLag" ->
                    Optional.of("{job=\"docker\"} |= \"apollo\"");
            default -> Optional.empty();
        };

        return query.map(q -> lokiQuery.queryRecentLogs(q, start, end, 30))
                .orElse(List.of());
    }

    private List<String> collectConcurrentAlerts(Long currentAlertId) {
        return alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc()
                .stream()
                .filter(e -> !e.getId().equals(currentAlertId))
                .map(AlertEvent::getAlertName)
                .filter(n -> n != null && !n.isBlank())
                .distinct()
                .limit(5)
                .toList();
    }

    @SuppressWarnings("unchecked")
    private Map<String, String> parseLabels(String labelsJson) {
        if (labelsJson == null || labelsJson.isBlank()) return Map.of();
        try {
            return objectMapper.readValue(labelsJson, Map.class);
        } catch (Exception e) {
            log.warn("labels JSON 파싱 실패: {}", labelsJson);
            return Map.of();
        }
    }
}
