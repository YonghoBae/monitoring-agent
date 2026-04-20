package io.ohgnoy.monitoring.infrastructure.loki;

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
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;

@Service
public class LokiQueryService {

    private static final Logger log = LoggerFactory.getLogger(LokiQueryService.class);
    private static final DateTimeFormatter TIME_FMT = DateTimeFormatter.ofPattern("HH:mm:ss")
            .withZone(ZoneId.systemDefault());

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String baseUrl;

    public LokiQueryService(RestClient.Builder builder,
                            @Value("${loki.url}") String lokiUrl,
                            ObjectMapper objectMapper) {
        this.restClient = builder.build();
        this.baseUrl = lokiUrl;
        this.objectMapper = objectMapper;
    }

    /**
     * LogQL 쿼리로 최근 로그 조회. 실패 시 빈 리스트 반환.
     * Promtail 설정: job=docker, container_id 레이블
     */
    public List<String> queryRecentLogs(String logqlQuery, Instant start, Instant end, int limit) {
        try {
            // URI.create()로 전달해 RestClient의 추가 인코딩 방지, +는 %20으로 교체
            String fullUri = baseUrl + "/loki/api/v1/query_range?query="
                    + URLEncoder.encode(logqlQuery, StandardCharsets.UTF_8).replace("+", "%20")
                    + "&start=" + (start.getEpochSecond() * 1_000_000_000L)
                    + "&end=" + (end.getEpochSecond() * 1_000_000_000L)
                    + "&limit=" + limit
                    + "&direction=backward";
            String response = restClient.get()
                    .uri(java.net.URI.create(fullUri))
                    .retrieve()
                    .body(String.class);

            return parseLogs(response);
        } catch (Exception e) {
            log.warn("Loki 쿼리 실패 [{}]: {}", logqlQuery, e.getMessage());
            return List.of();
        }
    }

    private List<String> parseLogs(String responseBody) throws Exception {
        JsonNode root = objectMapper.readTree(responseBody);
        if (!"success".equals(root.path("status").asText())) return List.of();

        List<String[]> entries = new ArrayList<>(); // [nanosec_ts, log_line]
        for (JsonNode stream : root.path("data").path("result")) {
            for (JsonNode entry : stream.path("values")) {
                String tsNs = entry.get(0).asText();
                String line = entry.get(1).asText();
                entries.add(new String[]{tsNs, line});
            }
        }

        // backward 방향이므로 역순 정렬해 오래된 순서로
        entries.sort((a, b) -> a[0].compareTo(b[0]));

        List<String> result = new ArrayList<>();
        for (String[] entry : entries) {
            Instant ts = Instant.ofEpochSecond(Long.parseLong(entry[0]) / 1_000_000_000L);
            String line = entry[1].length() > 300 ? entry[1].substring(0, 300) + "..." : entry[1];
            result.add("[" + TIME_FMT.format(ts) + "] " + line);
        }
        return result;
    }
}
