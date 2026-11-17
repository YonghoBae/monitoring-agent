package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import io.ohgnoy.monitoring.application.agent.*;
import io.ohgnoy.monitoring.application.agent.evaluation.*;
import io.ohgnoy.monitoring.application.agent.tools.WebSearchTool;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.playbook.ActionRecommendation;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.retry.support.RetryTemplate;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import static org.mockito.Mockito.*;

/** Opt-in actual-model comparison with immutable numeric synthetic worlds. */
@Tag("eval")
@EnabledIfEnvironmentVariable(named = "EVAL_BASE_URL", matches = "https?://.+")
class GroundedEvalRunner {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final ObjectMapper YAML = new ObjectMapper(new YAMLFactory());
    private record Judgment(EvaluationOracle.Verdict verdict, String raw, String model, int promptTokens, int completionTokens) { }

    @Test
    void evaluate() throws Exception {
        Path output = Path.of("build", "eval", "grounded-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss")));
        Files.createDirectories(output);
        ChatClient judge = client(env("EVAL_JUDGE_BASE_URL", env("EVAL_BASE_URL", "")), env("EVAL_JUDGE_MODEL", "qwen3:8b"), 3072);
        JsonNode calibration = resource("eval-judge-calibration-v1.yml");
        ObjectNode calibrationReport = calibrate(judge, calibration, output);
        write(output.resolve("conditions.json"), Map.of(
                "dataset", "eval-dataset-v3.yml", "synthetic", true,
                "arms", env("EVAL_ARMS", "v1,v2,v4"), "repeats", Integer.parseInt(env("EVAL_REPEATS", "3")),
                "agentModelRequested", env("EVAL_MODEL", "qwen3:8b"), "judgeModelRequested", env("EVAL_JUDGE_MODEL", "qwen3:8b"),
                "sameJudgeEndpoint", env("EVAL_JUDGE_BASE_URL", env("EVAL_BASE_URL", "")).equals(env("EVAL_BASE_URL", "")),
                "calibrationStatus", calibrationReport, "humanValidation", "pending", "timestamp", Instant.now().toString()));
        if (env("EVAL_CALIBRATION_ONLY", "false").equals("true")) return;
        ChatClient agentClient = client(env("EVAL_BASE_URL", ""), env("EVAL_MODEL", "qwen3:8b"), 1536);
        var noJudge = new AgentJudgeEvaluator(provider(null), mock(AgentEvaluationRepository.class), JSON, false, 1.0);
        var web = mock(WebSearchTool.class);
        when(web.web_search(anyString())).thenReturn("외부 검색은 이 합성 평가에서 제공하지 않습니다. 현재 관측으로 확인 불가한 내용은 가설로 구분하세요.");
        List<String> arms = Arrays.asList(env("EVAL_ARMS", "v1,v2,v4").split(","));
        int repeats = Integer.parseInt(env("EVAL_REPEATS", "3"));
        if (repeats < 1) throw new IllegalArgumentException("EVAL_REPEATS must be positive");
        List<JsonNode> scenarios = new ArrayList<>();
        resource("eval-dataset-v3.yml").path("scenarios").forEach(s -> {
            if (env("EVAL_ONLY", "").isBlank() || s.path("id").asText().equals(env("EVAL_ONLY", ""))) scenarios.add(s);
        });
        if (scenarios.isEmpty()) throw new IllegalArgumentException("No matching scenarios");
        List<ObjectNode> records = new ArrayList<>(); Random random = new Random(20261103);
        int total = scenarios.size() * repeats * arms.size(), done = 0;
        for (JsonNode original : scenarios) {
            ObjectNode scenario = original.deepCopy();
            scenario.putObject("policy").put("permission", scenario.path("playbook").path("category").asText());
            try (var world = new NumericEvalWorld(scenario)) {
                for (int rep = 1; rep <= repeats; rep++) {
                    List<String> order = new ArrayList<>(arms); Collections.shuffle(order, random);
                    for (String arm : order) {
                        world.resetTrace();
                        System.out.printf("GROUNDED %d/%d scenario=%s arm=%s rep=%d%n", ++done, total, scenario.path("id").asText(), arm, rep);
                        var factory = world.toolsFactory();
                        var agent = new ReActAgent(provider(agentClient), provider(new ReflectionAdvisor(agentClient)), factory, web, noJudge, arm);
                        var alert = new AlertEvent(scenario.path("alert").path("severity").asText().equals("critical") ? "CRITICAL" : "WARNING",
                                scenario.path("alert").path("message").asText(), scenario.path("alert").path("name").asText(),
                                scenario.path("alert").path("labels").toString(), null, null, world.evaluationTime.minusSeconds(600), null);
                        var playbook = scenario.path("playbook");
                        var recommendation = new ActionRecommendation(playbook.path("description").asText(),
                                ActionRecommendation.Category.valueOf(playbook.path("category").asText()),
                                playbook.path("command").isTextual() ? playbook.path("command").asText() : null);
                        long begin = System.nanoTime();
                        AgentResult result = agent.runWithContext(alert, recommendation,
                                "\n[합성 평가의 고정 기준 시각] " + world.evaluationTime
                                        + "\n상대 시간·현재 상태는 이 데이터 시각 기준이다. 도구 호출 로그의 wall-clock 시각과 구분한다. 읽기 전용 조사이며 실제 변경·외부 검색은 제공되지 않는다.");
                        long elapsed = (System.nanoTime() - begin) / 1_000_000;
                        ObjectNode trace = world.trace(); Judgment judgment = judge(judge, scenario, result, trace);
                        ObjectNode record = JSON.createObjectNode();
                        record.put("scenarioId", scenario.path("id").asText()).put("arm", arm).put("rep", rep)
                                .put("latencyMs", elapsed).put("toolCalls", result.iterationCount())
                                .put("status", judgment.verdict.status()).put("judgeModelReported", judgment.model)
                                .put("judgePromptTokens", judgment.promptTokens).put("judgeCompletionTokens", judgment.completionTokens)
                                .put("approvalPolicyExercised", !trace.path("events").isEmpty())
                                .put("calibrationPassed", calibrationReport.path("allMatched").asBoolean())
                                .put("independentHumanValidated", false);
                        record.set("result", JSON.valueToTree(result)); record.set("trace", trace);
                        record.set("judgment", JSON.valueToTree(judgment.verdict)); record.put("rawJudge", judgment.raw);
                        records.add(record); append(output.resolve("results.jsonl"), record);
                        writeProgress(output, records, total, calibrationReport);
                    }
                }
            } catch (Exception failure) {
                ObjectNode error = JSON.createObjectNode().put("scenarioId", scenario.path("id").asText()).put("status", "fixture_error").put("error", failure.toString());
                append(output.resolve("errors.jsonl"), error);
                throw failure; // A broken world is not a failed agent task.
            }
        }
        writeProgress(output, records, total, calibrationReport);
        System.out.println("GROUNDED_COMPLETE " + output.toAbsolutePath());
    }

    private ObjectNode calibrate(ChatClient judge, JsonNode fixture, Path output) throws Exception {
        int matched = 0, total = 0, ungraded = 0, falseSupport = 0;
        for (JsonNode group : fixture.path("cases")) for (JsonNode candidate : group.path("candidates")) {
            JsonNode trace = candidate.has("actual_trace_override") ? candidate.get("actual_trace_override") : group.path("actual_trace");
            var result = new AgentResult(candidate.path("answer").asText(), "", 0, null);
            Judgment judgment = judge(judge, group.path("scenario"), result, trace);
            String expected = candidate.path("expected_status").asText(), actual = judgment.verdict.status();
            boolean equal = expected.equals(actual); total++; if (equal) matched++;
            if (!judgment.verdict.graded()) ungraded++;
            if (!expected.equals("supported") && actual.equals("supported")) falseSupport++;
            ObjectNode row = JSON.createObjectNode().put("caseId", group.path("id").asText()).put("candidateId", candidate.path("id").asText())
                    .put("expected", expected).put("actual", actual).put("matched", equal).put("modelReported", judgment.model).put("rawJudge", judgment.raw);
            row.set("judgment", JSON.valueToTree(judgment.verdict)); append(output.resolve("calibration.jsonl"), row);
            System.out.printf("CALIBRATION %d %s/%s expected=%s actual=%s%n", total, group.path("id").asText(), candidate.path("id").asText(), expected, actual);
        }
        ObjectNode report = JSON.createObjectNode().put("total", total).put("matched", matched).put("ungraded", ungraded)
                .put("falseSupport", falseSupport).put("allMatched", total > 0 && matched == total)
                .put("annotationStatus", fixture.path("annotation_status").asText()).put("humanValidated", false);
        write(output.resolve("calibration-summary.json"), report); return report;
    }

    private Judgment judge(ChatClient client, JsonNode scenario, AgentResult result, JsonNode trace) {
        try {
            // Candidate IDs, labels, expected calibration status and prompt arm are not sent.
            var response = client.prompt().system(EvaluationOracle.systemPrompt())
                    .user(EvaluationOracle.userPrompt(scenario, result, trace)).call().chatResponse();
            String raw = response.getResult().getOutput().getText();
            var usage = response.getMetadata().getUsage();
            return new Judgment(EvaluationOracle.assess(raw, scenario, trace, result.conclusion()), raw, response.getMetadata().getModel(),
                    usage == null || usage.getPromptTokens() == null ? 0 : usage.getPromptTokens(),
                    usage == null || usage.getCompletionTokens() == null ? 0 : usage.getCompletionTokens());
        } catch (Exception e) { return new Judgment(EvaluationOracle.assess("", scenario, trace), "JUDGE_ERROR: " + e, "unknown", 0, 0); }
    }

    private void writeProgress(Path output, List<ObjectNode> records, int total, ObjectNode calibration) throws Exception {
        ObjectNode progress = JSON.createObjectNode().put("completed", records.size()).put("planned", total)
                .put("rankingValidated", false).put("calibrationMatched", calibration.path("matched").asInt()).put("calibrationTotal", calibration.path("total").asInt());
        for (String arm : env("EVAL_ARMS", "v1,v2,v4").split(",")) {
            var rows = records.stream().filter(r -> r.path("arm").asText().equals(arm)).toList(); ObjectNode counts = progress.putObject(arm);
            for (String status : List.of("supported", "partial", "unsupported", "uncertain", "ungraded_judge"))
                counts.put(status, rows.stream().filter(r -> r.path("status").asText().equals(status)).count());
            counts.put("n", rows.size());
        }
        write(output.resolve("progress.json"), progress);
        Files.writeString(output.resolve("summary.md"), "# Grounded evaluation\n\n" + records.size() + "/" + total + " runs.\n\n"
                + "Judge author-annotation checks: " + calibration.path("matched") + "/" + calibration.path("total")
                + ". Human validation pending; same-model Judge may be biased. No validated prompt ranking or production accuracy claim.\n\n"
                + "Structured per-arm outcomes: see progress.json. Actual observations and reasoning: results.jsonl.\n", StandardCharsets.UTF_8);
    }
    private static ChatClient client(String url, String model, int maxTokens) {
        return ChatClient.builder(OpenAiChatModel.builder().openAiApi(OpenAiApi.builder().baseUrl(url).apiKey(env("EVAL_API_KEY", "ollama")).build())
                .defaultOptions(OpenAiChatOptions.builder().model(model).temperature(0.0).maxTokens(maxTokens).reasoningEffort("none").build())
                .retryTemplate(RetryTemplate.builder().maxAttempts(1).build()).build()).build();
    }
    private static JsonNode resource(String name) throws Exception { try (var input = GroundedEvalRunner.class.getResourceAsStream("/" + name)) { return YAML.readTree(input); } }
    private static void append(Path path, Object value) throws Exception { Files.writeString(path, JSON.writeValueAsString(value) + "\n", StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND); }
    private static void write(Path path, Object value) throws Exception { Files.writeString(path, JSON.writerWithDefaultPrettyPrinter().writeValueAsString(value), StandardCharsets.UTF_8); }
    private static String env(String name, String fallback) { String value = System.getenv(name); return value == null || value.isBlank() ? fallback : value; }
    @SuppressWarnings("unchecked") private static <T> ObjectProvider<T> provider(T value) { ObjectProvider<T> provider = mock(ObjectProvider.class); when(provider.getIfAvailable()).thenReturn(value); return provider; }
}
