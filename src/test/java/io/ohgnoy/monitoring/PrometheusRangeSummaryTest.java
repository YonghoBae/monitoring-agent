package io.ohgnoy.monitoring;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import static org.assertj.core.api.Assertions.*;

class PrometheusRangeSummaryTest {
    private String summarize(String expression, String samples) throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/v1/query_range", exchange -> {
            byte[] body = ("{\"status\":\"success\",\"data\":{\"result\":" + samples + "}}")
                    .getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body); exchange.close();
        });
        server.start();
        try {
            var service = new PrometheusQueryService(RestClient.builder(), "http://127.0.0.1:" + server.getAddress().getPort(), new ObjectMapper());
            return service.querySummary("metric", expression, Instant.ofEpochSecond(0), Instant.ofEpochSecond(60));
        } finally { server.stop(0); }
    }
    @Test void durationsAndAlreadyScaledExpressionsKeepTheirMagnitude() throws Exception {
        String samples = "[{\"metric\":{\"instance\":\"site\"},\"values\":[[0,\"6.1\"],[60,\"6.2\"]]}]";
        assertThat(summarize("probe_duration_seconds", samples)).contains("현재=6.2", "site", "표본시각=60").doesNotContain("620");
        assertThat(summarize("100 * used_bytes / total_bytes", samples)).contains("현재=6.2").doesNotContain("GB", "MB", "620");
    }
    @Test void everyReturnedSeriesKeepsLabelsAndInvalidLatestIsNotBackfilled() throws Exception {
        String samples = "[{\"metric\":{\"datname\":\"first\"},\"values\":[[0,\"82\"],[60,\"NaN\"]]},"
                + "{\"metric\":{\"datname\":\"second\"},\"values\":[[60,\"7\"]]}]";
        assertThat(summarize("pg_stat_activity_count", samples)).contains("first", "second", "현재값 유효하지 않음", "현재=7.0").doesNotContain("현재=82");
    }
}
