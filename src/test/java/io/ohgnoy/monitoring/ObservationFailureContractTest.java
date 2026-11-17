package io.ohgnoy.monitoring;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import io.ohgnoy.monitoring.infrastructure.loki.LokiQueryService;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import java.net.InetSocketAddress;
import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ObservationFailureContractTest {
    @Test
    void unavailableLokiIsNotAnEmptySuccessfulLogQuery() throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/loki/api/v1/query_range", exchange -> { exchange.sendResponseHeaders(503, -1); exchange.close(); });
        server.start();
        try {
            var service = new LokiQueryService(RestClient.builder(), "http://127.0.0.1:" + server.getAddress().getPort(), new ObjectMapper());
            assertThatThrownBy(() -> service.queryRecentLogs("{job=\"docker\"}", Instant.now().minusSeconds(60), Instant.now(), 10))
                    .isInstanceOf(IllegalStateException.class);
        } finally { server.stop(0); }
    }
}
