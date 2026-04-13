package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.service.AlertVectorService;
import io.ohgnoy.monitoring.agent.service.AlertVerifier;
import io.ohgnoy.monitoring.agent.service.CommandExecutorService;
import io.ohgnoy.monitoring.agent.service.LokiQueryService;
import io.ohgnoy.monitoring.agent.service.PrometheusQueryService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.document.Document;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * ReAct 에이전트가 사용할 도구 모음.
 * Spring AI @Tool 어노테이션으로 Gemini function calling 스키마에 자동 등록된다.
 *
 * 각 메서드 호출은 reasoningLog에 기록되어 추론 과정 추적에 활용된다.
 */
public class AgentTools {

    private static final Logger log = LoggerFactory.getLogger(AgentTools.class);
    private static final Pattern ALLOWED_CONTAINER_NAME = Pattern.compile("^[a-zA-Z0-9][a-zA-Z0-9_.\\-]*$");

    private final AlertVerifier alertVerifier;
    private final PrometheusQueryService prometheusQuery;
    private final LokiQueryService lokiQuery;
    private final AlertVectorService vectorService;
    private final CommandExecutorService commandExecutorService;

    // 현재 실행 중인 ReAct 루프의 추론 로그
    private final StringBuilder reasoningLog = new StringBuilder();
    private int callCount = 0;
    // per-request 캐시: ReAct 루프 내 중복 Docker API 호출 방지
    private List<String> cachedContainers;

    public AgentTools(AlertVerifier alertVerifier,
                      PrometheusQueryService prometheusQuery,
                      LokiQueryService lokiQuery,
                      AlertVectorService vectorService,
                      CommandExecutorService commandExecutorService) {
        this.alertVerifier = alertVerifier;
        this.prometheusQuery = prometheusQuery;
        this.lokiQuery = lokiQuery;
        this.vectorService = vectorService;
        this.commandExecutorService = commandExecutorService;
    }

    @Tool(description = "Prometheus에서 해당 알람이 현재도 발생 중인지 확인한다.")
    public String verify_alert(
            @ToolParam(description = "알람 이름 (예: ContainerDown, HighCpuLoad)") String alertName,
            @ToolParam(description = "알람 레이블 JSON 문자열 (예: {\"name\":\"nginx\"})") String labelsJson) {
        log.info("[AgentTool] verify_alert: alertName={}", alertName);
        String result = alertVerifier.verify(alertName, labelsJson).toPromptLine();
        appendLog("verify_alert", "alertName=" + alertName, result);
        return result;
    }

    @Tool(description = "Prometheus에서 사용 가능한 메트릭 이름 목록을 조회한다. query_prometheus 호출 전 정확한 메트릭 이름이 불확실할 때 먼저 호출해 확인한다.")
    public String list_metrics(
            @ToolParam(description = "메트릭 이름에 포함된 키워드 (예: 'DCGM', 'container', 'node', 'gpu')") String filter) {
        log.info("[AgentTool] list_metrics: filter={}", filter);
        List<String> metrics = prometheusQuery.listMetrics(filter);
        String result = metrics.isEmpty() ? "메트릭 없음: " + filter : String.join(", ", metrics);
        appendLog("list_metrics", "filter=" + filter, result);
        return result;
    }

    @Tool(description = "Prometheus에서 PromQL 메트릭을 조회한다. 메트릭 이름이 불확실하면 list_metrics를 먼저 호출해 확인한다.")
    public String query_prometheus(
            @ToolParam(description = "PromQL 표현식 (예: rate(container_cpu_usage_seconds_total[5m]))") String promql,
            @ToolParam(description = "조회할 과거 시간 범위 (분 단위, 예: '30')") String timeRangeMinutes) {
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

    @Tool(description = "현재 실행 중인 Docker 컨테이너 이름 목록을 반환한다. query_loki 호출 전 조회해서 존재하는 컨테이너인지 확인할 수 있다.")
    public String get_containers() {
        List<String> containers = getContainersCached();
        String result = containers.isEmpty() ? "실행 중인 컨테이너 없음" : String.join(", ", containers);
        appendLog("get_containers", "", result);
        return result;
    }

    private List<String> getContainersCached() {
        if (cachedContainers == null) {
            cachedContainers = commandExecutorService.listContainers();
        }
        return cachedContainers;
    }

    @Tool(description = "Loki에서 컨테이너 로그를 조회한다.")
    public String query_loki(
            @ToolParam(description = "Docker 컨테이너 이름") String containerName,
            @ToolParam(description = "조회할 과거 시간 범위 (분 단위, 예: '30')") String timeRangeMinutes) {
        log.info("[AgentTool] query_loki: container={}", containerName);

        // 1차: 실행 중인 컨테이너 목록 대조 (캐시 활용)
        List<String> running = getContainersCached();
        if (!running.isEmpty() && !running.contains(containerName)) {
            return "존재하지 않는 컨테이너: " + containerName + ". 실행 중인 컨테이너: " + String.join(", ", running);
        }

        // 2차: 메타문자 검증 (목록 조회 실패 시 폴백, defense-in-depth)
        if (!ALLOWED_CONTAINER_NAME.matcher(containerName).matches()) {
            return "허용되지 않는 컨테이너 이름: " + containerName;
        }

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

    @Tool(description = "과거 알람 및 해결 사례를 지식베이스에서 검색한다.")
    public String search_rag(
            @ToolParam(description = "자연어 검색어 (예: 'nginx 컨테이너 OOM 재시작')") String query) {
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
