package io.ohgnoy.monitoring.agent.service.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Tavily API를 이용한 웹 검색 도구.
 * search_rag와 Gemini 자체 지식으로 해결이 불가능할 때 최후의 수단으로 사용한다.
 *
 * tavily.api-key가 설정되지 않으면 비활성 상태로 동작한다.
 */
@Component
public class WebSearchTool {

    private static final Logger log = LoggerFactory.getLogger(WebSearchTool.class);
    private static final String TAVILY_URL = "https://api.tavily.com/search";

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String apiKey;

    public WebSearchTool(RestClient.Builder builder,
                         ObjectMapper objectMapper,
                         @Value("${tavily.api-key:}") String apiKey) {
        this.restClient = builder.baseUrl(TAVILY_URL).build();
        this.objectMapper = objectMapper;
        this.apiKey = apiKey;
    }

    @Tool(description = "인터넷에서 에러 메시지나 알람 증상에 대한 정보를 검색한다. search_rag와 Gemini 자체 지식으로 해결이 불가능할 때만 사용하는 최후의 수단.")
    public String web_search(String query) {
        if (apiKey == null || apiKey.isBlank()) {
            log.warn("[WebSearchTool] Tavily API 키 미설정 — web_search 비활성");
            return "웹 검색 기능이 설정되지 않았습니다.";
        }

        log.info("[WebSearchTool] web_search: query={}", query);
        try {
            Map<String, Object> body = Map.of(
                    "api_key", apiKey,
                    "query", query,
                    "max_results", 3,
                    "search_depth", "basic"
            );

            String response = restClient.post()
                    .uri("")
                    .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(String.class);

            return parseResults(response);
        } catch (Exception e) {
            log.warn("[WebSearchTool] 웹 검색 실패: {}", e.getMessage());
            return "웹 검색 실패: " + e.getMessage();
        }
    }

    private String parseResults(String responseBody) throws Exception {
        JsonNode root = objectMapper.readTree(responseBody);
        JsonNode results = root.path("results");

        if (results.isEmpty()) return "검색 결과 없음.";

        List<String> items = new ArrayList<>();
        for (JsonNode r : results) {
            String title = r.path("title").asText("");
            String content = r.path("content").asText("");
            String url = r.path("url").asText("");
            if (!title.isBlank() || !content.isBlank()) {
                String snippet = content.length() > 300 ? content.substring(0, 300) + "..." : content;
                items.add("- " + title + "\n  " + snippet + "\n  출처: " + url);
            }
        }
        return items.isEmpty() ? "검색 결과 없음." : String.join("\n\n", items);
    }
}
