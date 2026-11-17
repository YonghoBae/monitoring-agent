package io.ohgnoy.monitoring;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.HashMap;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PrometheusMetricDiscoveryTest {
    private static final List<String> NAMES = List.of("node_memory_MemAvailable_bytes", "node_memory_MemTotal_bytes",
            "DCGM_FI_DEV_GPU_UTIL", "DCGM_FI_DEV_FB_USED", "node_cpu_seconds_total");
    private final ObjectMapper mapper = new ObjectMapper();
    private final Map<String, String> overrides = new HashMap<>();
    private HttpServer server;
    private PrometheusQueryService service;

    @BeforeEach
    void startPrometheusFixture() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/v1/label/__name__/values", exchange -> {
            List<String> names = NAMES;
            String query = exchange.getRequestURI().getRawQuery();
            if (query != null) {
                String selector = URLDecoder.decode(query.substring(query.indexOf('=') + 1), StandardCharsets.UTF_8);
                String quotedRegex = selector.substring(selector.indexOf("=~") + 2, selector.length() - 1);
                String regex = mapper.readTree(quotedRegex).asText();
                Pattern pattern = Pattern.compile(regex);
                names = NAMES.stream().filter(name -> pattern.matcher(name).matches()).toList();
            }
            byte[] body = mapper.writeValueAsBytes(java.util.Map.of("status", "success", "data", names));
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.createContext("/api/v1/query", exchange -> {
            String metric = URLDecoder.decode(exchange.getRequestURI().getRawQuery().substring("query=".length()), StandardCharsets.UTF_8);
            String value = overrides.getOrDefault(metric, switch (metric) {
                case "node_memory_MemTotal_bytes" -> "17179869184";
                case "node_memory_MemAvailable_bytes" -> "6442450944";
                case "DCGM_FI_DEV_GPU_UTIL" -> "35";
                case "DCGM_FI_DEV_FB_USED" -> "1024";
                case "DCGM_FI_DEV_FB_FREE" -> "3072";
                default -> metric.contains("node_cpu_seconds_total") ? "12"
                        : metric.contains("node_filesystem") ? "40"
                        : metric.contains("node_network_") ? "2048" : "NaN";
            });
            var sample = java.util.Map.of("metric", java.util.Map.of("instance", "host:9100", "gpu", "0", "modelName", "Test GPU"),
                    "value", List.of(1, value));
            byte[] body = mapper.writeValueAsBytes(java.util.Map.of("status", "success", "data", java.util.Map.of("result", List.of(sample))));
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        service = new PrometheusQueryService(RestClient.builder(), "http://127.0.0.1:" + server.getAddress().getPort(), mapper);
    }

    @AfterEach
    void stopPrometheusFixture() {
        server.stop(0);
    }

    @Test
    void commaSeparatedMemoryAndGpuFindsBothFamiliesIncludingFramebuffer() {
        assertThat(service.listMetrics("memory, gpu")).containsExactlyElementsOf(NAMES.subList(0, 4));
    }

    @Test
    void koreanRamAndGpuAliasesWorkCaseInsensitively() {
        assertThat(service.listMetrics("램 GPU")).containsExactlyElementsOf(NAMES.subList(0, 4));
    }

    @Test
    void filterTermsAreLiteralRatherThanArbitraryRegex() {
        assertThat(service.listMetrics("memory,.*")).containsExactlyElementsOf(NAMES.subList(0, 2));
    }

    @Test
    void blankFilterPreservesUnfilteredDiscovery() {
        assertThat(service.listMetrics(" ")).containsExactlyElementsOf(NAMES);
    }

    @Test
    void hardwareSnapshotUsesRealValuesAndExplicitUnitsWithoutInventedLabels() {
        assertThat(service.hardwareSummary()).contains("16.00 GiB", "6.00 GiB", "10.00 GiB", "62.5%",
                "35.0%", "1024 MiB", "3072 MiB", "Test GPU", "host:9100");
    }

    @Test
    void unavailableGpuUtilDoesNotDiscardHealthyRamAndVram() {
        overrides.put("DCGM_FI_DEV_GPU_UTIL", "NaN");
        String[] result = new String[1];
        assertThatCode(() -> result[0] = service.hardwareSummary()).doesNotThrowAnyException();
        assertThat(result[0]).contains("16.00 GiB", "62.5%", "1024 MiB", "DCGM_FI_DEV_GPU_UTIL", "유효하지 않은");
    }

    @Test
    void invalidAvailableRamDoesNotDiscardGpuOrRamTotal() {
        overrides.put("node_memory_MemAvailable_bytes", "+Inf");
        String[] result = new String[1];
        assertThatCode(() -> result[0] = service.hardwareSummary()).doesNotThrowAnyException();
        assertThat(result[0]).contains("16.00 GiB", "35.0%", "3072 MiB", "node_memory_MemAvailable_bytes", "유효하지 않은");
    }

    @Test
    void connectionFailuresAreNotReportedAsEmptyMetrics() {
        server.stop(0);
        assertThatThrownBy(() -> service.listMetrics("cpu")).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> service.querySummary("cpu", "up", java.time.Instant.now().minusSeconds(60), java.time.Instant.now()))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void systemSnapshotReturnsExplicitUnitsAndIsolatedFailures() {
        assertThat(service.systemSummary("cpu")).contains("CPU", "%", "host:9100");
        assertThat(service.systemSummary("disk")).contains("디스크", "%");
        assertThat(service.systemSummary("network")).contains("B/s");
    }
}
