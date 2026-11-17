package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import io.ohgnoy.monitoring.application.agent.AgentResult;
import io.ohgnoy.monitoring.application.agent.ReActAgent;
import io.ohgnoy.monitoring.application.agent.ReflectionAdvisor;
import io.ohgnoy.monitoring.application.agent.evaluation.AgentEvaluationRepository;
import io.ohgnoy.monitoring.application.agent.evaluation.AgentJudgeEvaluator;
import io.ohgnoy.monitoring.application.agent.evaluation.JudgeEvaluationResult;
import io.ohgnoy.monitoring.application.agent.tools.AgentToolsFactory;
import io.ohgnoy.monitoring.application.agent.tools.WebSearchTool;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.playbook.ActionRecommendation;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.loki.LokiQueryService;
import io.ohgnoy.monitoring.infrastructure.prometheus.AlertVerifier;
import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import io.ohgnoy.monitoring.infrastructure.prometheus.VerificationResult;
import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.retry.support.RetryTemplate;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.function.ToIntFunction;

import static org.junit.jupiter.api.Assumptions.assumeTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 라이브 평가 러너 — 실제 LLM으로 에이전트/Judge를 실행하되
 * 관측 데이터(Prometheus/Loki/RAG)는 시나리오별 mock으로 고정해 재현성을 확보한다.
 *
 * 실행: SPRING_AI_GOOGLE_GENAI_API_KEY=... ./gradlew evalRun
 * (기본 test 태스크에서는 @Tag("eval") 제외 — CI에서 실행되지 않는다)
 *
 * 측정 설계:
 *  - arm: v1(baseline 프롬프트) vs v2(현재 운영 프롬프트) — A/B 비교
 *  - 반복: EVAL_REPEATS회 (기본 3) — 에이전트 변동성 측정
 *  - Judge: temperature 0 (AgentConfig), 시나리오 정답 기준 주입
 *  - 출력: build/eval/run-<ts>/results.jsonl + summary.md + human-grading.md
 */
@Tag("eval")
@SpringBootTest
@DisplayName("라이브 평가 러너 (수동 실행 전용)")
class LiveEvalRunner {

    // EVAL_ARMS로 비교할 프롬프트 버전 지정 (예: "v1,v3")
    private static final String[] ARMS = env("EVAL_ARMS", "v1,v2").split(",");
    private static final String[] DIMENSIONS = {"factuality", "tool_use", "actionability", "safety"};

    @Autowired @Qualifier("agentChatClient") ObjectProvider<ChatClient> agentClientProvider;
    @Autowired @Qualifier("judgeChatClient") ObjectProvider<ChatClient> judgeClientProvider;
    @Autowired WebSearchTool webSearchTool;
    @Autowired ObjectMapper objectMapper;

    @DynamicPropertySource
    static void evalProperties(DynamicPropertyRegistry registry) {
        String apiKey = resolveApiKey();
        if (apiKey != null) {
            registry.add("spring.ai.google.genai.api-key", () -> apiKey);
        }
        registry.add("spring.ai.google.genai.chat.options.model",
                () -> env("EVAL_MODEL", "gemini-2.5-flash"));
        // Judge는 평가 대상과 다른(더 강한) 모델 — 같은 모델의 자기 응답 선호 편향 회피
        registry.add("judge.model", () -> env("EVAL_JUDGE_MODEL", "gemini-2.5-pro"));
    }

    private static String resolveApiKey() {
        String key = System.getenv("SPRING_AI_GOOGLE_GENAI_API_KEY");
        if (key == null || key.isBlank()) {
            key = System.getenv("GEMINI_API_KEY");
        }
        return (key == null || key.isBlank()) ? null : key;
    }

    private static String env(String name, String defaultValue) {
        String value = System.getenv(name);
        return (value == null || value.isBlank()) ? defaultValue : value;
    }

    @Test
    @DisplayName("전체 시나리오 × 프롬프트 arm × 반복 실행 후 통계 산출")
    void runLiveEvaluation() throws Exception {
        boolean local = !env("EVAL_BASE_URL", "").isBlank();
        assumeTrue(local || resolveApiKey() != null,
                "EVAL_BASE_URL 또는 Gemini API 키 미설정 — 라이브 평가 건너뜀");
        ChatClient agentClient = local ? openAiClient(env("EVAL_BASE_URL", ""), env("EVAL_MODEL", "qwen3:8b"))
                : agentClientProvider.getIfAvailable();
        ChatClient judgeClient = local ? openAiClient(env("EVAL_JUDGE_BASE_URL", env("EVAL_BASE_URL", "")),
                env("EVAL_JUDGE_MODEL", "qwen3:8b")) : judgeClientProvider.getIfAvailable();
        assumeTrue(agentClient != null && judgeClient != null, "ChatClient 빈 없음 — 라이브 평가 건너뜀");

        int repeats = Integer.parseInt(env("EVAL_REPEATS", "3"));
        long sleepMs = Long.parseLong(env("EVAL_SLEEP_MS", "0"));
        String onlyScenario = env("EVAL_ONLY", "");   // 단일 시나리오 디버깅용

        JsonNode root = loadDataset();
        List<String> defaultContainers = toStringList(root.get("default_containers"));

        Path outDir = Path.of("build", "eval",
                "run-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss")));
        Files.createDirectories(outDir);
        Path resultsFile = outDir.resolve("results.jsonl");
        Files.writeString(outDir.resolve("conditions.json"), objectMapper.writeValueAsString(Map.of(
                "agentModel", env("EVAL_MODEL", local ? "qwen3:8b" : "gemini-2.5-flash"),
                "judgeModel", env("EVAL_JUDGE_MODEL", local ? "qwen3:8b" : "gemini-2.5-pro"),
                "local", local, "sharedRuntimeGuard", true, "repeats", repeats,
                "sameEndpointJudge", local && env("EVAL_JUDGE_BASE_URL", env("EVAL_BASE_URL", "")).equals(env("EVAL_BASE_URL", "")),
                "fixtureMode", "strict-summary-v1")));

        // Judge 프롬프트 빌드/파싱 재사용을 위한 헬퍼 인스턴스 (evaluate()는 호출하지 않음)
        AgentJudgeEvaluator judgeHelper = new AgentJudgeEvaluator(
                providerOf(null), mock(AgentEvaluationRepository.class), objectMapper, false, 1.0);
        // ReActAgent 내부 자동 평가는 비활성 인스턴스로 차단 (Judge는 러너가 직접 동기 호출)
        AgentJudgeEvaluator noopJudge = new AgentJudgeEvaluator(
                providerOf(null), mock(AgentEvaluationRepository.class), objectMapper, false, 1.0);
        ReflectionAdvisor reflectionAdvisor = new ReflectionAdvisor(agentClient);

        List<ObjectNode> records = new ArrayList<>();
        int runId = 0;
        int total = countRuns(root, onlyScenario, repeats);

        for (JsonNode scenario : root.get("scenarios")) {
            String scenarioId = scenario.get("id").asText();
            if (!onlyScenario.isBlank() && !onlyScenario.equals(scenarioId)) {
                continue;
            }
            for (String arm : ARMS) {
                for (int rep = 1; rep <= repeats; rep++) {
                    runId++;
                    System.out.printf("%n[eval %d/%d] scenario=%s arm=%s rep=%d%n",
                            runId, total, scenarioId, arm, rep);

                    ObjectNode record = executeSingleRun(
                            scenario, arm, rep, runId, agentClient, judgeClient,
                            reflectionAdvisor, noopJudge, judgeHelper, defaultContainers);
                    records.add(record);
                    Files.writeString(resultsFile, record.toString() + "\n",
                            StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND);

                    if (sleepMs > 0) {
                        Thread.sleep(sleepMs);
                    }
                }
            }
        }

        writeSummary(outDir, records, repeats);
        writeHumanGradingSheet(outDir, records.stream().filter(r -> !r.path("fixtureUnsupported").asBoolean()).toList());
        System.out.println("\n평가 완료 — 결과: " + outDir.toAbsolutePath());
    }

    private ChatClient openAiClient(String url, String model) {
        var options = OpenAiChatOptions.builder().model(model).temperature(0.0).maxTokens(1536).reasoningEffort("none").build();
        var chatModel = OpenAiChatModel.builder()
                .openAiApi(OpenAiApi.builder().baseUrl(url).apiKey(env("EVAL_API_KEY", "ollama")).build())
                .defaultOptions(options).retryTemplate(RetryTemplate.builder().maxAttempts(1).build()).build();
        return ChatClient.builder(chatModel).build();
    }

    // ──────────────────────────────────────────────
    // 단일 실행
    // ──────────────────────────────────────────────

    private ObjectNode executeSingleRun(JsonNode scenario, String arm, int rep, int runId,
                                        ChatClient agentClient, ChatClient judgeClient,
                                        ReflectionAdvisor reflectionAdvisor, AgentJudgeEvaluator noopJudge,
                                        AgentJudgeEvaluator judgeHelper, List<String> defaultContainers) {
        AlertEvent alert = buildAlert(scenario.get("alert"));
        ActionRecommendation recommendation = buildRecommendation(scenario.get("playbook"));
        List<String> inventory = scenario.at("/mocks/containers").isArray()
                ? toStringList(scenario.at("/mocks/containers")) : defaultContainers;
        StrictObservationFixture fixture = new StrictObservationFixture(scenario, inventory);
        AgentToolsFactory factory = buildMockedToolsFactory(scenario, defaultContainers, fixture);

        ReActAgent agent = new ReActAgent(
                providerOf(agentClient), providerOf(reflectionAdvisor),
                factory, webSearchTool, noopJudge, arm);

        long startNanos = System.nanoTime();
        AgentResult result = runAgentWithRetry(agent, alert, recommendation);
        long latencyMs = (System.nanoTime() - startNanos) / 1_000_000;
        boolean infraError = isInfraFailure(result);

        String criteria = buildCriteriaText(scenario.get("expected"));
        JudgeEvaluationResult judged;
        if (fixture.hasUnsupportedQueries()) {
            judged = JudgeEvaluationResult.parseFailed("Unsupported fixture computation; agent outcome ungraded");
        } else try {
            String judgeResponse = judgeClient.prompt()
                    .system(judgeHelper.buildJudgeSystemPrompt())
                    .user(judgeHelper.buildEvaluationPrompt(alert, result, criteria))
                    .call()
                    .content();
            judged = judgeHelper.parseJudgeResponse(judgeResponse);
        } catch (Exception e) {
            judged = JudgeEvaluationResult.parseFailed("judge 호출 실패: " + e.getMessage());
        }

        boolean pass = !fixture.hasUnsupportedQueries() && passesMinimumScores(judged, scenario.at("/expected/minimum_scores"));
        System.out.printf("  toolCalls=%d latency=%dms scores=[F%d T%d A%d S%d] verdict=%s pass=%s%n",
                result.iterationCount(), latencyMs,
                judged.factuality().score(), judged.tool_use().score(),
                judged.actionability().score(), judged.safety().score(),
                judged.verdict(), pass);

        ObjectNode record = objectMapper.createObjectNode();
        record.put("runId", runId);
        record.put("scenarioId", scenario.get("id").asText());
        record.put("arm", arm);
        record.put("rep", rep);
        record.put("latencyMs", latencyMs);
        record.put("toolCalls", result.iterationCount());
        record.put("reflection", result.reflectionResult() == null ? "" : result.reflectionResult());
        record.put("factuality", judged.factuality().score());
        record.put("tool_use", judged.tool_use().score());
        record.put("actionability", judged.actionability().score());
        record.put("safety", judged.safety().score());
        record.put("overall", judged.overallScore());
        record.put("verdict", fixture.hasUnsupportedQueries() ? "ungraded_fixture" : judged.verdict());
        record.put("parseFailed", !fixture.hasUnsupportedQueries() && judged.parse_failed());
        record.put("fixtureUnsupported", fixture.hasUnsupportedQueries());
        record.put("evaluationStatus", fixture.hasUnsupportedQueries() ? "ungraded_fixture" : "graded");
        record.set("unsupportedQueries", objectMapper.valueToTree(fixture.unsupportedQueries()));
        record.put("infraError", infraError);
        record.put("pass", pass);
        record.put("conclusion", result.conclusion());
        record.put("reasoningLog", result.reasoningChain());
        record.put("judgeFactualityReason", judged.factuality().reason());
        record.put("judgeSafetyReason", judged.safety().reason());
        return record;
    }

    /** LLM 빈 응답 등 인프라성 실패는 1회 재시도 — 에이전트 행동 측정을 오염시키지 않기 위함 */
    private AgentResult runAgentWithRetry(ReActAgent agent, AlertEvent alert, ActionRecommendation recommendation) {
        AgentResult result = runAgentOnce(agent, alert, recommendation);
        if (isInfraFailure(result)) {
            System.out.println("  인프라 실패 감지 — 1회 재시도");
            result = runAgentOnce(agent, alert, recommendation);
        }
        return result;
    }

    private AgentResult runAgentOnce(ReActAgent agent, AlertEvent alert, ActionRecommendation recommendation) {
        try {
            return agent.run(alert, recommendation);
        } catch (Exception e) {
            return new AgentResult("실행 실패: " + e.getMessage(), "", 0, null);
        }
    }

    private boolean isInfraFailure(AgentResult result) {
        return result.conclusion() == null
                || result.conclusion().startsWith("AI 분석 실패")
                || result.conclusion().startsWith("실행 실패");
    }

    private boolean passesMinimumScores(JudgeEvaluationResult judged, JsonNode minimums) {
        return judged.factuality().score() >= minimums.get("factuality").asInt()
                && judged.tool_use().score() >= minimums.get("tool_use").asInt()
                && judged.actionability().score() >= minimums.get("actionability").asInt()
                && judged.safety().score() >= minimums.get("safety").asInt();
    }

    // ──────────────────────────────────────────────
    // 시나리오 → 도메인 객체 변환
    // ──────────────────────────────────────────────

    private AlertEvent buildAlert(JsonNode alertNode) {
        String level = "critical".equals(alertNode.get("severity").asText()) ? "CRITICAL" : "WARNING";
        String labelsJson = alertNode.has("labels") ? alertNode.get("labels").toString() : "{}";
        String summary = alertNode.has("summary") ? alertNode.get("summary").asText() : null;
        return new AlertEvent(level, alertNode.get("message").asText(),
                alertNode.get("name").asText(), labelsJson, summary, null, Instant.now(), null);
    }

    private ActionRecommendation buildRecommendation(JsonNode playbook) {
        String command = playbook.get("command").isNull() ? null : playbook.get("command").asText();
        return new ActionRecommendation(
                playbook.get("description").asText(),
                ActionRecommendation.Category.valueOf(playbook.get("category").asText()),
                command);
    }

    /** 시나리오 mock으로 고정된 관측 계층을 가진 AgentToolsFactory 생성 */
    AgentToolsFactory buildMockedToolsFactory(JsonNode scenario, List<String> defaultContainers, StrictObservationFixture fixture) {
        JsonNode mocks = scenario.get("mocks");
        AlertVerifier verifier = mock(AlertVerifier.class);
        when(verifier.verify(any(), any())).thenAnswer(inv -> toVerificationResult(fixture.verify(inv.getArgument(0), inv.getArgument(1))));

        List<String> metrics = toStringList(mocks.get("metrics"));
        PrometheusQueryService prometheus = mock(PrometheusQueryService.class);
        when(prometheus.listMetrics(any())).thenReturn(metrics);
        when(prometheus.querySummary(any(), anyString(), any(Instant.class), any(Instant.class)))
                .thenAnswer(inv -> fixture.query(inv.getArgument(1), inv.getArgument(2), inv.getArgument(3)));
        when(prometheus.systemSummary(anyString())).thenAnswer(inv -> {
            String scope = inv.getArgument(0);
            if (!List.of("all", "cpu", "disk", "network").contains(scope)) return "잘못된 resource 값: all, cpu, disk, network 중 선택";
            List<String> rows = new ArrayList<>();
            JsonNode values = mocks.get("prometheus");
            if (values != null) for (JsonNode entry : values) {
                String key = entry.path("keyword").asText().toLowerCase();
                boolean relevant = switch (scope) {
                    case "cpu" -> key.contains("cpu");
                    case "disk" -> key.contains("filesystem");
                    case "network" -> key.contains("network");
                    default -> key.contains("cpu") || key.contains("filesystem") || key.contains("network");
                };
                if (relevant) rows.add(entry.path("response").asText());
            }
            return rows.isEmpty() ? "데이터 없음: " + scope : String.join("\n", rows);
        });
        when(prometheus.hardwareSummary()).thenAnswer(inv -> {
            List<String> rows = new ArrayList<>();
            JsonNode values = mocks.get("prometheus");
            if (values != null) for (JsonNode entry : values) {
                String key = entry.path("keyword").asText().toLowerCase();
                if (key.contains("memory") || key.contains("dcgm") || key.contains("gpu")) rows.add(entry.path("response").asText());
            }
            return rows.isEmpty() ? "RAM/GPU 현재 데이터 없음" : String.join("\n", rows);
        });

        LokiQueryService loki = mock(LokiQueryService.class);
        when(loki.queryRecentLogs(anyString(), any(Instant.class), any(Instant.class), anyInt()))
                .thenAnswer(inv -> fixture.logs(inv.getArgument(0), inv.getArgument(1), inv.getArgument(2), inv.getArgument(3)));

        AlertVectorService vector = mock(AlertVectorService.class);
        when(vector.searchSimilar(any(), anyInt())).thenReturn(toRagDocuments(mocks.get("rag")));

        CommandExecutorService command = mock(CommandExecutorService.class);
        List<String> containers = mocks.has("containers")
                ? toStringList(mocks.get("containers")) : defaultContainers;
        when(command.listContainers()).thenReturn(containers);

        return new AgentToolsFactory(verifier, prometheus, loki, vector, command);
    }

    private VerificationResult toVerificationResult(JsonNode verify) {
        return switch (VerificationResult.Status.valueOf(verify.get("status").asText())) {
            case CONFIRMED -> VerificationResult.confirmed(
                    verify.get("value").asText(),
                    verify.has("activeAt") ? verify.get("activeAt").asText() : Instant.now().toString());
            case STALE -> VerificationResult.stale();
            case UNKNOWN -> VerificationResult.unknown();
        };
    }

    private List<Document> toRagDocuments(JsonNode rag) {
        List<Document> docs = new ArrayList<>();
        if (rag != null) {
            for (JsonNode r : rag) {
                docs.add(new Document(r.get("text").asText(),
                        Map.of("type", r.get("type").asText(), "outcome", r.get("outcome").asText())));
            }
        }
        return docs;
    }

    private String buildCriteriaText(JsonNode expected) {
        StringBuilder sb = new StringBuilder();
        sb.append("must_check (반드시 확인했어야 하는 것):\n");
        expected.get("must_check").forEach(n -> sb.append("- ").append(n.asText()).append("\n"));
        sb.append("acceptable_actions (허용되는 권고):\n");
        expected.get("acceptable_actions").forEach(n -> sb.append("- ").append(n.asText()).append("\n"));
        sb.append("forbidden_actions (제안하면 실패인 조치):\n");
        expected.get("forbidden_actions").forEach(n -> sb.append("- ").append(n.asText()).append("\n"));
        return sb.toString();
    }

    // ──────────────────────────────────────────────
    // 통계 및 리포트
    // ──────────────────────────────────────────────

    void writeSummary(Path outDir, List<ObjectNode> allRecords, int repeats) throws IOException {
        long unsupported = count(allRecords, r -> r.path("fixtureUnsupported").asBoolean());
        if (unsupported > 0) {
            Files.writeString(outDir.resolve("summary.md"), "# Evaluation incomplete\n\n"
                    + "총 " + allRecords.size() + "건 중 " + unsupported + "건은 기존 fixture의 계산·레이블 정보 부족으로 미판정입니다.\n"
                    + "모델 실패나 Judge 파싱 실패가 아니며, 이 실행의 프롬프트 간 합격률 비교는 생성하지 않습니다.\n"
                    + "results.jsonl의 evaluationStatus/unsupportedQueries를 확인하세요.\n", StandardCharsets.UTF_8);
            return;
        }
        long infraErrors = count(allRecords, r -> r.get("infraError").asBoolean());
        long judgeFailures = count(allRecords, r -> r.get("parseFailed").asBoolean());
        // 인프라 실패·judge 실패 레코드는 0점으로 평균을 왜곡하므로 점수 통계에서 제외
        List<ObjectNode> records = allRecords.stream()
                .filter(r -> !r.get("infraError").asBoolean() && !r.get("parseFailed").asBoolean())
                .toList();

        StringBuilder md = new StringBuilder();
        md.append("# Live Eval Summary\n\n");
        md.append("- 실행 시각: ").append(LocalDateTime.now()).append("\n");
        md.append("- 에이전트 모델: ").append(env("EVAL_MODEL", "gemini-2.5-flash")).append("\n");
        md.append("- Judge 모델: ").append(env("EVAL_JUDGE_MODEL", "gemini-2.5-pro"))
                .append(" (temperature=0; 독립성은 conditions.json과 실제 엔드포인트 설정 확인)\n");
        if (!env("EVAL_BASE_URL", "").isBlank()) md.append("- 로컬 평가: 동일 모델 Judge일 수 있으므로 독립적인 품질 검증으로 해석하지 않음\n");
        md.append("- 모든 arm에 현재 공통 실행 제한 적용: 과거 런타임과 동일한 비교가 아님\n");
        md.append("- 반복: ").append(repeats).append("회 / arm\n");
        md.append("- 총 실행: ").append(allRecords.size()).append("건")
                .append(" (통계 제외 — 인프라 실패: ").append(infraErrors)
                .append("건, judge 실패: ").append(judgeFailures).append("건)\n\n");

        md.append("## Arm 비교 (선택한 프롬프트 버전)\n\n");
        md.append("| arm | n | factuality (mean/p50/p95) | tool_use | actionability | safety | overall mean | pass rate | parse fail | avg tool calls | avg latency(ms) |\n");
        md.append("|-----|---|---------------------------|----------|---------------|--------|--------------|-----------|------------|----------------|------------------|\n");
        for (String arm : ARMS) {
            List<ObjectNode> armRecords = records.stream()
                    .filter(r -> arm.equals(r.get("arm").asText())).toList();
            if (armRecords.isEmpty()) {
                continue;
            }
            md.append("| ").append(arm).append(" | ").append(armRecords.size()).append(" | ");
            for (String dim : DIMENSIONS) {
                md.append(statLine(armRecords, r -> r.get(dim).asInt())).append(" | ");
            }
            md.append(String.format("%.2f", mean(armRecords, r -> r.get("overall").asDouble()))).append(" | ");
            md.append(String.format("%.0f%%", 100.0 * count(armRecords, r -> r.get("pass").asBoolean()) / armRecords.size())).append(" | ");
            md.append(count(armRecords, r -> r.get("parseFailed").asBoolean())).append(" | ");
            md.append(String.format("%.1f", mean(armRecords, r -> r.get("toolCalls").asDouble()))).append(" | ");
            md.append(String.format("%.0f", mean(armRecords, r -> r.get("latencyMs").asDouble()))).append(" |\n");
        }

        md.append("\n## 시나리오별 overall 평균\n\n");
        md.append("| scenario | v1 | v2 | Δ |\n|----------|----|----|---|\n");
        Map<String, Map<String, List<Double>>> byScenario = new HashMap<>();
        for (ObjectNode r : records) {
            byScenario.computeIfAbsent(r.get("scenarioId").asText(), k -> new HashMap<>())
                    .computeIfAbsent(r.get("arm").asText(), k -> new ArrayList<>())
                    .add(r.get("overall").asDouble());
        }
        byScenario.entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(entry -> {
            double v1 = entry.getValue().getOrDefault("v1", List.of()).stream()
                    .mapToDouble(Double::doubleValue).average().orElse(Double.NaN);
            double v2 = entry.getValue().getOrDefault("v2", List.of()).stream()
                    .mapToDouble(Double::doubleValue).average().orElse(Double.NaN);
            md.append(String.format("| %s | %.2f | %.2f | %+.2f |%n", entry.getKey(), v1, v2, v2 - v1));
        });

        md.append("\n## 측정 조건\n\n");
        md.append("- 관측 데이터(Prometheus/Loki/RAG/컨테이너 목록)는 시나리오별 고정 mock — 재현 가능\n");
        md.append("- 에이전트 LLM: 운영과 동일 경로(ReActAgent + ReflectionAdvisor), temperature 기본값\n");
        md.append("- Judge LLM: temperature 0, 시나리오별 정답 기준(must_check/forbidden_actions) 주입\n");
        md.append("- pass = 4개 차원 모두 시나리오별 minimum_scores 이상\n");

        Files.writeString(outDir.resolve("summary.md"), md.toString(), StandardCharsets.UTF_8);
    }

    private String statLine(List<ObjectNode> records, ToIntFunction<ObjectNode> extractor) {
        List<Integer> values = records.stream().map(extractor::applyAsInt).sorted().toList();
        double mean = values.stream().mapToInt(Integer::intValue).average().orElse(0);
        return String.format("%.1f / %d / %d", mean, percentile(values, 50), percentile(values, 95));
    }

    private int percentile(List<Integer> sorted, int p) {
        if (sorted.isEmpty()) {
            return 0;
        }
        int index = (int) Math.ceil(p / 100.0 * sorted.size()) - 1;
        return sorted.get(Math.max(0, Math.min(index, sorted.size() - 1)));
    }

    private double mean(List<ObjectNode> records, java.util.function.ToDoubleFunction<ObjectNode> f) {
        return records.stream().mapToDouble(f).average().orElse(0);
    }

    private long count(List<ObjectNode> records, java.util.function.Predicate<ObjectNode> p) {
        return records.stream().filter(p).count();
    }

    /**
     * 사람 채점용 blind 시트 — arm 라벨을 숨긴 무작위 표본을 출력한다.
     * 채점 후 human-grading-key.csv와 대조해 Judge 점수와의 방향 일치율을 계산한다.
     */
    private void writeHumanGradingSheet(Path outDir, List<ObjectNode> records) throws IOException {
        int sampleSize = Integer.parseInt(env("EVAL_HUMAN_SAMPLE", "15"));
        List<ObjectNode> shuffled = new ArrayList<>(records.stream()
                .filter(r -> !r.get("infraError").asBoolean()).toList());
        java.util.Collections.shuffle(shuffled, new Random(42));  // 고정 seed — 표본 재현 가능
        List<ObjectNode> sample = shuffled.stream()
                .limit(Math.min(sampleSize, shuffled.size()))
                .sorted(Comparator.comparingInt(r -> r.get("runId").asInt()))
                .toList();

        StringBuilder md = new StringBuilder();
        md.append("# Human Grading Sheet (blind)\n\n");
        md.append("각 응답을 0~10으로 채점: Factuality / Tool Use / Actionability / Safety.\n");
        md.append("arm(프롬프트 버전)은 의도적으로 숨김 — 채점 후 human-grading-key.csv와 대조.\n\n");

        StringBuilder key = new StringBuilder("runId,scenarioId,arm,rep\n");
        for (ObjectNode r : sample) {
            md.append("---\n\n## Run #").append(r.get("runId").asInt()).append("\n\n");
            md.append("**시나리오**: ").append(r.get("scenarioId").asText()).append("\n\n");
            md.append("**도구 호출 로그**:\n```\n").append(r.get("reasoningLog").asText()).append("\n```\n\n");
            md.append("**에이전트 결론**:\n\n").append(r.get("conclusion").asText()).append("\n\n");
            md.append("**사람 채점**: Factuality __ / Tool Use __ / Actionability __ / Safety __\n\n");
            key.append(r.get("runId").asInt()).append(',')
                    .append(r.get("scenarioId").asText()).append(',')
                    .append(r.get("arm").asText()).append(',')
                    .append(r.get("rep").asInt()).append('\n');
        }
        Files.writeString(outDir.resolve("human-grading.md"), md.toString(), StandardCharsets.UTF_8);
        Files.writeString(outDir.resolve("human-grading-key.csv"), key.toString(), StandardCharsets.UTF_8);
    }

    // ──────────────────────────────────────────────
    // 유틸
    // ──────────────────────────────────────────────

    private JsonNode loadDataset() throws IOException {
        ObjectMapper yaml = new ObjectMapper(new YAMLFactory());
        try (InputStream in = LiveEvalRunner.class.getResourceAsStream("/eval-dataset-v2.yml")) {
            return yaml.readTree(in);
        }
    }

    private int countRuns(JsonNode root, String onlyScenario, int repeats) {
        int scenarios = 0;
        for (JsonNode s : root.get("scenarios")) {
            if (onlyScenario.isBlank() || onlyScenario.equals(s.get("id").asText())) {
                scenarios++;
            }
        }
        return scenarios * ARMS.length * repeats;
    }

    private List<String> toStringList(JsonNode array) {
        List<String> list = new ArrayList<>();
        if (array != null) {
            array.forEach(n -> list.add(n.asText()));
        }
        return list;
    }

    private static <T> ObjectProvider<T> providerOf(T value) {
        return new ObjectProvider<>() {
            @Override public T getObject(Object... args) { return value; }
            @Override public T getObject() { return value; }
            @Override public T getIfAvailable() { return value; }
            @Override public T getIfUnique() { return value; }
        };
    }
}
