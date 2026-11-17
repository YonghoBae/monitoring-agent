package io.ohgnoy.monitoring.infrastructure.prometheus;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import java.net.http.HttpClient;
import java.time.Duration;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.Map;
import java.util.LinkedHashMap;

@Service
public class PrometheusQueryService {

    private static final Logger log = LoggerFactory.getLogger(PrometheusQueryService.class);

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String baseUrl;

    public PrometheusQueryService(RestClient.Builder builder,
                                  @Value("${prometheus.url}") String prometheusUrl,
                                  ObjectMapper objectMapper) {
        var requestFactory = new JdkClientHttpRequestFactory(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build());
        requestFactory.setReadTimeout(Duration.ofSeconds(15));
        this.restClient = builder.requestFactory(requestFactory).build();
        this.baseUrl = prometheusUrl;
        this.objectMapper = objectMapper;
    }

    /**
     * 쉼표/공백/파이프로 나눈 키워드 중 하나를 포함하는 메트릭 이름 목록을 반환한다.
     * Prometheus /api/v1/label/__name__/values 의 match[] 파라미터로 서버 측 필터링.
     */
    public List<String> listMetrics(String filter) {
        try {
            String uri;
            String selector = metricSelector(filter);
            if (selector != null) {
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
            if (!"success".equals(root.path("status").asText())) throw new IllegalStateException("Prometheus discovery failed");

            List<String> metrics = new ArrayList<>();
            for (JsonNode name : root.path("data")) {
                metrics.add(name.asText());
            }
            return metrics;
        } catch (Exception e) {
            log.warn("메트릭 목록 조회 실패 [{}]: {}", filter, e.getMessage());
            throw new IllegalStateException("Prometheus 메트릭 목록 조회 실패", e);
        }
    }

    private String metricSelector(String filter) {
        if (filter == null || filter.isBlank()) return null;
        Set<String> terms = new LinkedHashSet<>();
        for (String word : filter.toLowerCase(Locale.ROOT).split("[,\\s|]+")) {
            if (word.isBlank()) continue;
            if (Set.of("ram", "램", "메모리").contains(word)) {
                terms.add("memory");
            } else if (Set.of("gpu", "vram", "그래픽", "지피유", "nvidia").contains(word)) {
                terms.add("gpu");
                terms.add("dcgm");
            } else {
                terms.add(word);
            }
        }
        if (terms.isEmpty()) return null;
        String regex = "(?i).*(" + terms.stream().map(Pattern::quote).collect(Collectors.joining("|")) + ").*";
        // Regex quoting and PromQL string quoting are separate escaping layers.
        return "{__name__=~\"" + regex.replace("\\", "\\\\").replace("\"", "\\\"") + "\"}";
    }

    /** Fixed, read-only snapshot: the model does not invent metric names or labels. */
    public String hardwareSummary() {
        String[] names = {"node_memory_MemTotal_bytes", "node_memory_MemAvailable_bytes",
                "DCGM_FI_DEV_GPU_UTIL", "DCGM_FI_DEV_FB_USED", "DCGM_FI_DEV_FB_FREE"};
        Map<String, JsonNode> samples = new LinkedHashMap<>();
        List<String> issues = new ArrayList<>();
        for (String name : names) {
            if (Thread.currentThread().isInterrupted()) throw new IllegalStateException("조회 중단");
            try {
                String uri = baseUrl + "/api/v1/query?query=" + URLEncoder.encode(name, StandardCharsets.UTF_8);
                String response = restClient.get().uri(java.net.URI.create(uri)).retrieve().body(String.class);
                JsonNode root = objectMapper.readTree(response);
                if (!"success".equals(root.path("status").asText())) throw new IllegalStateException("Prometheus query failed");
                JsonNode result = root.path("data").path("result");
                samples.put(name, result);
                if (result.isEmpty()) issues.add(name + ": 현재 조회 결과 없음 (수집 중단으로 단정하지 않음)");
            } catch (Exception e) {
                log.warn("하드웨어 메트릭 조회 실패 [{}]: {}", name, e.getMessage());
                samples.put(name, objectMapper.createArrayNode());
                issues.add(name + ": 조회 실패");
            }
        }
        Map<String, Double> available = new LinkedHashMap<>();
        for (JsonNode sample : samples.get(names[1])) {
            Double value = sampleValue(sample, names[1], issues);
            if (value != null) available.put(sampleIdentity(sample), value);
        }
        StringBuilder result = new StringBuilder("실제 Prometheus RAM/GPU 조회 결과 (수집 대상 instance 기준):\n");
        for (JsonNode sample : samples.get(names[0])) {
            Double total = sampleValue(sample, names[0], issues);
            if (total == null) continue;
            Double free = available.get(sampleIdentity(sample));
            String instance = sample.path("metric").path("instance").asText("unknown");
            result.append(String.format(Locale.ROOT, "RAM [%s]: 전체 %.2f GiB", instance, total / 1073741824.0));
            if (free != null && total > 0 && free <= total) {
                result.append(String.format(Locale.ROOT, ", 사용 가능 %.2f GiB, 사용 %.2f GiB (%.1f%%)",
                        free / 1073741824.0, (total - free) / 1073741824.0, 100 * (total - free) / total));
            }
            result.append('\n');
        }
        String[] labels = {"GPU 사용률", "GPU VRAM 사용", "GPU VRAM 여유"};
        for (int i = 2; i < names.length; i++) {
            for (JsonNode sample : samples.get(names[i])) {
                Double number = sampleValue(sample, names[i], issues);
                if (number == null) continue;
                JsonNode metric = sample.path("metric");
                String identity = metric.path("instance").asText("unknown") + ", gpu=" + metric.path("gpu").asText("unknown")
                        + ", " + metric.path("modelName").asText("model unknown");
                String value = i == 2 ? String.format(Locale.ROOT, "%.1f%%", number)
                        : String.format(Locale.ROOT, "%.0f MiB", number);
                result.append(labels[i - 2]).append(" [").append(identity).append("]: ").append(value).append('\n');
            }
        }
        issues.forEach(issue -> result.append(issue).append('\n'));
        return result.toString();
    }

    /** Fixed PromQL converts counters into rates before presenting resource usage. */
    public String systemSummary(String resource) {
        List<String> results = new ArrayList<>();
        String scope = resource == null ? "all" : resource.toLowerCase(Locale.ROOT).trim();
        if (!Set.of("all", "cpu", "disk", "network").contains(scope)) return "잘못된 resource 값: all, cpu, disk, network 중 선택";
        if (scope.equals("all") || scope.equals("cpu")) {
            results.add(instantSummary("CPU 사용률", "100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])))", "%"));
        }
        if (scope.equals("all") || scope.equals("disk")) {
            results.add(instantSummary("디스크 사용률", "100 * (1 - node_filesystem_avail_bytes{fstype!~\"tmpfs|overlay|squashfs\"} / node_filesystem_size_bytes{fstype!~\"tmpfs|overlay|squashfs\"})", "%"));
        }
        if (scope.equals("all") || scope.equals("network")) {
            results.add(instantSummary("네트워크 수신", "rate(node_network_receive_bytes_total{device!=\"lo\"}[5m])", "B/s"));
            results.add(instantSummary("네트워크 송신", "rate(node_network_transmit_bytes_total{device!=\"lo\"}[5m])", "B/s"));
        }
        return String.join("\n", results);
    }

    private String instantSummary(String label, String expr, String unit) {
        if (Thread.currentThread().isInterrupted()) throw new IllegalStateException("조회 중단");
        try {
            String uri = baseUrl + "/api/v1/query?query=" + URLEncoder.encode(expr, StandardCharsets.UTF_8);
            JsonNode root = objectMapper.readTree(restClient.get().uri(java.net.URI.create(uri)).retrieve().body(String.class));
            if (!"success".equals(root.path("status").asText())) throw new IllegalStateException("Prometheus query failed");
            JsonNode samples = root.path("data").path("result");
            if (samples.isEmpty()) return label + ": 현재 데이터 없음 (확인 불가)";
            List<String> rows = new ArrayList<>();
            for (JsonNode sample : samples) {
                double value = Double.parseDouble(sample.path("value").path(1).asText());
                if (!Double.isFinite(value) || value < 0 || (unit.equals("%") && value > 100)) {
                    rows.add(label + " [" + sample.path("metric") + "]: 유효하지 않은 값 (확인 불가)");
                } else {
                    rows.add(String.format(Locale.ROOT, "%s [%s]: %.2f %s", label, sample.path("metric"), value, unit));
                }
            }
            return String.join("\n", rows);
        } catch (Exception e) {
            log.warn("자원 상태 조회 실패 [{}]: {}", label, e.toString());
            return label + ": Prometheus 조회 실패 (확인 불가)";
        }
    }

    private String sampleIdentity(JsonNode sample) {
        return sample.path("metric").path("job").asText() + "|" + sample.path("metric").path("instance").asText();
    }

    private Double sampleValue(JsonNode sample, String metric, List<String> issues) {
        try {
            double value = Double.parseDouble(sample.path("value").path(1).asText());
            if (!Double.isFinite(value) || value < 0
                    || (metric.equals("node_memory_MemTotal_bytes") && value == 0)
                    || (metric.equals("DCGM_FI_DEV_GPU_UTIL") && value > 100)
                    || (metric.startsWith("DCGM_") && value >= 9e18)) {
                throw new IllegalArgumentException("Invalid hardware sample");
            }
            return value;
        } catch (RuntimeException e) {
            issues.add(metric + " [" + sample.path("metric").path("instance").asText("unknown") + "]: 유효하지 않은 값, 이 항목만 제외");
            log.warn("하드웨어 메트릭 값 제외 [{}]", metric);
            return null;
        }
    }

    /**
     * PromQL range query를 실행하고 요약 문자열 반환.
     * 실패는 빈 결과와 구분해 호출자에게 전달한다.
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
            throw new IllegalStateException("Prometheus 조회 실패", e);
        }
    }

    private String parseAndSummarize(String label, String expr, String responseBody) throws Exception {
        JsonNode root = objectMapper.readTree(responseBody);
        if (!"success".equals(root.path("status").asText())) throw new IllegalStateException("Prometheus query failed");

        JsonNode results = root.path("data").path("result");
        if (results.isEmpty()) return label + ": 데이터 없음";

        // Arbitrary PromQL may change dimensions. Preserve its raw magnitude and labels.
        // Substring inference is unsafe: even "duration" contains "ratio".
        List<String> rows = new ArrayList<>();
        int limit = Math.min(results.size(), 20);
        for (int index = 0; index < limit; index++) {
            JsonNode series = results.get(index), values = series.path("values");
            String identity = label + " [" + series.path("metric") + "]";
            if (values.isEmpty()) { rows.add(identity + ": 데이터 없음"); continue; }
            List<Double> nums = new ArrayList<>();
            for (JsonNode pair : values) {
                double value = finiteSample(pair.path(1));
                if (Double.isFinite(value)) nums.add(value);
            }
            JsonNode latestPair = values.get(values.size() - 1);
            double latest = finiteSample(latestPair.path(1));
            if (!Double.isFinite(latest)) {
                rows.add(identity + ": 현재값 유효하지 않음 (확인 불가), 표본시각=" + latestPair.path(0));
                continue;
            }
            double min = nums.stream().mapToDouble(Double::doubleValue).min().orElse(latest);
            double max = nums.stream().mapToDouble(Double::doubleValue).max().orElse(latest);
            rows.add(identity + ": 최솟값=" + min + ", 최댓값=" + max + ", 현재=" + latest
                    + " (" + detectTrend(nums) + "), 표본시각=" + latestPair.path(0)
                    + ", 유효표본=" + nums.size() + "/" + values.size());
        }
        if (results.size() > limit) rows.add("시계열 " + results.size() + "개 중 " + limit + "개만 표시; 레이블 필터 필요");
        return "PromQL=" + expr + " (원시 수치; 단위는 표현식 기준, 자동 환산 없음)\n" + String.join("\n", rows);
    }

    private double finiteSample(JsonNode value) {
        try { return Double.parseDouble(value.asText()); }
        catch (NumberFormatException e) { return Double.NaN; }
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

}
