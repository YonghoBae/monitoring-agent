package io.ohgnoy.monitoring.infrastructure.prometheus;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

@Service
public class PrometheusQueryService {

    private static final Logger log = LoggerFactory.getLogger(PrometheusQueryService.class);

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String baseUrl;

    public PrometheusQueryService(RestClient.Builder builder,
                                  @Value("${prometheus.url}") String prometheusUrl,
                                  ObjectMapper objectMapper) {
        this.restClient = builder.build();
        this.baseUrl = prometheusUrl;
        this.objectMapper = objectMapper;
    }

    /**
     * filter 키워드를 포함하는 메트릭 이름 목록을 반환한다.
     * Prometheus /api/v1/label/__name__/values 의 match[] 파라미터로 서버 측 필터링.
     */
    public List<String> listMetrics(String filter) {
        try {
            String uri;
            if (filter != null && !filter.isBlank()) {
                String selector = "{__name__=~\".*" + filter + ".*\"}";
                uri = baseUrl + "/api/v1/label/__name__/values?match[]="
                        + URLEncoder.encode(selector, StandardCharsets.UTF_8).replace("+", "%20");
            } else {
                uri = baseUrl + "/api/v1/label/__name__/values";
            }

            String response = restClient.get()
                    .uri(java.net.URI.create(uri))
                    .retrieve()
                    .body(String.class);

            JsonNode root = objectMapper.readTree(response);
            if (!"success".equals(root.path("status").asText())) return List.of();

            List<String> metrics = new ArrayList<>();
            for (JsonNode name : root.path("data")) {
                metrics.add(name.asText());
            }
            return metrics;
        } catch (Exception e) {
            log.warn("메트릭 목록 조회 실패 [{}]: {}", filter, e.getMessage());
            return List.of();
        }
    }

    /**
     * PromQL range query를 실행하고 요약 문자열 반환.
     * 실패 시 null 반환 (alert 처리를 중단하지 않음).
     */
    public String querySummary(String label, String expr, Instant start, Instant end) {
        try {
            // URI.create()로 전달해 RestClient의 추가 인코딩 방지
            String fullUri = baseUrl + "/api/v1/query_range?query="
                    + URLEncoder.encode(expr, StandardCharsets.UTF_8).replace("+", "%20")
                    + "&start=" + start.getEpochSecond()
                    + "&end=" + end.getEpochSecond()
                    + "&step=60";
            String response = restClient.get()
                    .uri(java.net.URI.create(fullUri))
                    .retrieve()
                    .body(String.class);

            return parseAndSummarize(label, expr, response);
        } catch (Exception e) {
            log.warn("Prometheus 쿼리 실패 [{}]: {}", expr, e.getMessage());
            return null;
        }
    }

    private String parseAndSummarize(String label, String expr, String responseBody) throws Exception {
        JsonNode root = objectMapper.readTree(responseBody);
        if (!"success".equals(root.path("status").asText())) return null;

        JsonNode results = root.path("data").path("result");
        if (results.isEmpty()) return label + ": 데이터 없음";

        // 첫 번째 시계열 사용
        JsonNode values = results.get(0).path("values");
        if (values.isEmpty()) return null;

        List<Double> nums = new ArrayList<>();
        for (JsonNode pair : values) {
            try {
                nums.add(Double.parseDouble(pair.get(1).asText()));
            } catch (NumberFormatException ignored) {
            }
        }
        if (nums.isEmpty()) return null;

        double min = nums.stream().mapToDouble(Double::doubleValue).min().orElse(0);
        double max = nums.stream().mapToDouble(Double::doubleValue).max().orElse(0);
        double latest = nums.get(nums.size() - 1);
        String trend = detectTrend(nums);
        String fmt = selectFormat(expr);

        return String.format("%s: 최솟값=%s, 최댓값=%s, 현재=%s (%s)",
                label, format(min, fmt), format(max, fmt), format(latest, fmt), trend);
    }

    private String detectTrend(List<Double> values) {
        if (values.size() < 4) return "변동없음";
        int q = values.size() / 4;
        double firstAvg = values.subList(0, q).stream().mapToDouble(Double::doubleValue).average().orElse(0);
        double lastAvg = values.subList(values.size() - q, values.size()).stream().mapToDouble(Double::doubleValue).average().orElse(0);
        double diff = (lastAvg - firstAvg) / (Math.abs(firstAvg) + 1e-10);
        if (diff > 0.1) return "↑상승";
        if (diff < -0.1) return "↓하락";
        return "→유지";
    }

    private String selectFormat(String expr) {
        String lower = expr.toLowerCase();
        if (lower.contains("_bytes")) return "bytes";
        if (lower.contains("ratio") || lower.contains("/ node_memory_") || lower.contains("/ container_spec_memory")) return "percent";
        return "raw";
    }

    private String format(double value, String type) {
        return switch (type) {
            case "bytes" -> {
                if (value >= 1_073_741_824) yield String.format("%.1fGB", value / 1_073_741_824);
                if (value >= 1_048_576) yield String.format("%.1fMB", value / 1_048_576);
                yield String.format("%.0fB", value);
            }
            case "percent" -> String.format("%.1f%%", value * 100);
            default -> String.format("%.2f", value);
        };
    }
}
