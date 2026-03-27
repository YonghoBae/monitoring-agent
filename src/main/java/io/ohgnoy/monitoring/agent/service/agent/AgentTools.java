package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.service.AlertVectorService;
import io.ohgnoy.monitoring.agent.service.AlertVerifier;
import io.ohgnoy.monitoring.agent.service.LokiQueryService;
import io.ohgnoy.monitoring.agent.service.PrometheusQueryService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.document.Document;
import org.springframework.ai.tool.annotation.Tool;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.stream.Collectors;

/**
 * ReAct 에이전트가 사용할 도구 모음.
 * Spring AI @Tool 어노테이션으로 Gemini function calling 스키마에 자동 등록된다.
 *
 * 각 메서드 호출은 reasoningLog에 기록되어 추론 과정 추적에 활용된다.
 */
public class AgentTools {

    private static final Logger log = LoggerFactory.getLogger(AgentTools.class);

    private final AlertVerifier alertVerifier;
    private final PrometheusQueryService prometheusQuery;
    private final LokiQueryService lokiQuery;
    private final AlertVectorService vectorService;

    // 현재 실행 중인 ReAct 루프의 추론 로그
    private final StringBuilder reasoningLog = new StringBuilder();
    private int callCount = 0;

    public AgentTools(AlertVerifier alertVerifier,
                      PrometheusQueryService prometheusQuery,
                      LokiQueryService lokiQuery,
                      AlertVectorService vectorService) {
        this.alertVerifier = alertVerifier;
        this.prometheusQuery = prometheusQuery;
        this.lokiQuery = lokiQuery;
        this.vectorService = vectorService;
    }

    @Tool(description = "Prometheus에서 해당 알람이 현재도 발생 중인지 확인한다. alertName은 알람 이름, labelsJson은 알람 레이블 JSON 문자열.")
    public String verify_alert(String alertName, String labelsJson) {
        log.info("[AgentTool] verify_alert: alertName={}", alertName);
        String result = alertVerifier.verify(alertName, labelsJson).toPromptLine();
        appendLog("verify_alert", "alertName=" + alertName, result);
        return result;
    }

    @Tool(description = "Prometheus에서 PromQL 메트릭을 조회한다. promql은 PromQL 표현식, timeRangeMinutes는 조회할 과거 시간 범위(분 단위, 예: '30').")
    public String query_prometheus(String promql, String timeRangeMinutes) {
        log.info("[AgentTool] query_prometheus: promql={}", promql);
        try {
            int minutes = Integer.parseInt(timeRangeMinutes.trim());
            Instant end = Instant.now();
            Instant start = end.minus(minutes, ChronoUnit.MINUTES);
            String result = prometheusQuery.querySummary("metric", promql, start, end);
            String response = result != null ? result : "데이터 없음: " + promql;
            appendLog("query_prometheus", "promql=" + promql + ", range=" + timeRangeMinutes + "m", response);
            return response;
        } catch (NumberFormatException e) {
            return "잘못된 timeRangeMinutes 값: " + timeRangeMinutes;
        }
    }

    @Tool(description = "Loki에서 컨테이너 로그를 조회한다. containerName은 Docker 컨테이너 이름, timeRangeMinutes는 조회할 과거 시간 범위(분 단위, 예: '30').")
    public String query_loki(String containerName, String timeRangeMinutes) {
        log.info("[AgentTool] query_loki: container={}", containerName);
        try {
            int minutes = Integer.parseInt(timeRangeMinutes.trim());
            Instant end = Instant.now();
            Instant start = end.minus(minutes, ChronoUnit.MINUTES);
            String logql = "{job=\"docker\"} |= `" + containerName + "`";
            List<String> logs = lokiQuery.queryRecentLogs(logql, start, end, 30);
            String response = logs.isEmpty()
                    ? "로그 없음: " + containerName
                    : String.join("\n", logs);
            appendLog("query_loki", "container=" + containerName + ", range=" + timeRangeMinutes + "m", response);
            return response;
        } catch (NumberFormatException e) {
            return "잘못된 timeRangeMinutes 값: " + timeRangeMinutes;
        }
    }

    @Tool(description = "과거 알람 및 해결 사례를 지식베이스에서 검색한다. query는 자연어 검색어 (예: 'nginx 컨테이너 OOM 재시작').")
    public String search_rag(String query) {
        log.info("[AgentTool] search_rag: query={}", query);
        List<Document> docs = vectorService.searchSimilar(query, 5);
        String response;
        if (docs.isEmpty()) {
            response = "유사한 과거 사례 없음.";
        } else {
            response = docs.stream()
                    .map(d -> {
                        String type = (String) d.getMetadata().getOrDefault("type", "alert");
                        String outcome = (String) d.getMetadata().getOrDefault("outcome", "");
                        String suffix = outcome.isBlank() ? "" : " [" + outcome + "]";
                        return "- [" + type + "]" + suffix + " " + d.getText();
                    })
                    .collect(Collectors.joining("\n"));
        }
        appendLog("search_rag", "query=" + query, response);
        return response;
    }

    // ---- 추론 로그 관리 ----

    private void appendLog(String toolName, String input, String output) {
        callCount++;
        reasoningLog.append("\n[도구 호출 #").append(callCount).append("] ").append(toolName)
                .append("\n  입력: ").append(input)
                .append("\n  결과: ").append(truncate(output, 500))
                .append("\n");
    }

    private String truncate(String s, int max) {
        if (s == null) return "";
        return s.length() > max ? s.substring(0, max) + "..." : s;
    }

    public String getReasoningLog() {
        return reasoningLog.toString();
    }

    public int getCallCount() {
        return callCount;
    }
}
