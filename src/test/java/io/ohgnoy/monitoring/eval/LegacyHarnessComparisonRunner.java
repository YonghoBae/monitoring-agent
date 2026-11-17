package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.application.agent.FocusedInvestigator;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.retry.support.RetryTemplate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Duration;
import java.time.ZoneOffset;
import java.util.*;

/** Fresh controlled-regression run. Explicit driver attestation and opt-in required. */
@Tag("eval")
@EnabledIfEnvironmentVariable(named="RUN_LEGACY_HARNESS_COMPARISON", matches="1")
class LegacyHarnessComparisonRunner {
    static final ObjectMapper JSON = new ObjectMapper();
    static final List<String> ARMS = List.of("pi_plus", "compact_plus");
    static final String ORDER_POLICY = "within-family-ordinal-plus-repeat-plus-alternating-odd-family-phase-v1";

    record OrderPlan(Map<String,Integer> ordinals, Map<String,Integer> phases, Map<String,Integer> sizes) { }

    static OrderPlan orderPlan(JsonNode scenes) {
        var sizes = new LinkedHashMap<String,Integer>();
        var ordinals = new LinkedHashMap<String,Integer>();
        for (var scene : scenes) {
            String id = scene.path("id").asText(), family = scene.path("family").asText();
            if (id.isBlank() || family.isBlank()) throw new IllegalArgumentException("Missing case/family identity");
            int ordinal = sizes.merge(family, 1, Integer::sum) - 1;
            if (ordinals.put(id, ordinal) != null) throw new IllegalArgumentException("Duplicate case ID");
        }
        var phases = new LinkedHashMap<String,Integer>(); int oddIndex = 0;
        for (var family : sizes.entrySet()) {
            // Even families balance internally. Alternate the unavoidable one-slot
            // excess across odd families, in first-appearance order.
            phases.put(family.getKey(), family.getValue() % 2 == 0 ? 0 : oddIndex++ % 2);
        }
        return new OrderPlan(Collections.unmodifiableMap(ordinals), Collections.unmodifiableMap(phases),
                             Collections.unmodifiableMap(sizes));
    }

    static List<String> orderedArms(OrderPlan plan, JsonNode scene, int repeat) {
        if (repeat < 0 || repeat >= 3) throw new IllegalArgumentException("Expected repeat 0, 1, or 2");
        Integer ordinal = plan.ordinals().get(scene.path("id").asText());
        Integer phase = plan.phases().get(scene.path("family").asText());
        if (ordinal == null || phase == null) throw new IllegalArgumentException("Case not in order plan");
        var arms = new ArrayList<>(ARMS);
        Collections.rotate(arms, -Math.floorMod(ordinal + repeat + phase, 2));
        return List.copyOf(arms);
    }
    static void validatePublishedField(JsonNode field) {
        var keys = new HashSet<String>(); field.fieldNames().forEachRemaining(keys::add);
        if (!keys.equals(Set.of("key", "question", "type", "unit"))
                && !keys.equals(Set.of("key", "question", "type", "unit", "measurement")))
            throw new IllegalArgumentException("Only published key/question/type/unit and optional measurement allowed");
        if (!field.has("measurement")) return;
        var measurement = field.path("measurement");
        var measurementKeys = new HashSet<String>(); measurement.fieldNames().forEachRemaining(measurementKeys::add);
        if (!measurement.isObject() || !measurementKeys.equals(Set.of("lookback_seconds", "aggregation"))
                || !measurement.path("lookback_seconds").isIntegralNumber()
                || measurement.path("lookback_seconds").bigIntegerValue().signum() <= 0
                || !measurement.path("aggregation").isTextual()
                || !Set.of("rate", "increase").contains(measurement.path("aggregation").asText()))
            throw new IllegalArgumentException("Invalid published measurement definition");
    }

    @Test void compare() throws Exception {
        String datasetName = System.getenv("EVAL_DATASET"), manifestName = System.getenv("LEGACY_RUN_MANIFEST");
        String outputName = System.getenv("LEGACY_RAW_OUTPUT_DIR");
        if (datasetName == null || manifestName == null || outputName == null)
            throw new IllegalStateException("Use the gated run_legacy_eval_v5.py driver");
        var manifest = JSON.readTree(Files.readString(Path.of(manifestName)));
        byte[] source = Files.readAllBytes(Path.of(datasetName));
        String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(source));
        if (!manifest.path("preflight_verified").asBoolean(false) || !manifest.path("status").asText().equals("running")
                || !manifest.path("built_dataset_sha256").asText().equals(digest))
            throw new IllegalStateException("Missing/current-dataset preflight attestation");
        JsonNode dataset = JSON.readTree(source), scenes = dataset.path("scenarios");
        if (!scenes.isArray() || scenes.size() != 35) throw new IllegalArgumentException("Expected all 35 legacy test scenes");
        int fields = 0;
        for (var scene : scenes) {
            if (!scene.path("split").asText().equals("test")) throw new IllegalArgumentException("Test split only");
            for (var field : scene.path("answer_fields")) {
                validatePublishedField(field);
                fields++;
            }
        }
        if (fields != 81) throw new IllegalArgumentException("Expected 62 original plus 19 explicitly requested clause fields");
        var plan = orderPlan(scenes);
        Path folder = Path.of(outputName); Files.createDirectories(folder);
        if (Files.exists(folder.resolve("results.jsonl"))) throw new IllegalStateException("Do not overwrite previous answers");
        String model = HarnessComparisonRunner.env("EVAL_MODEL", "qwen3.5:9b-pi32k");
        String url = HarnessComparisonRunner.env("EVAL_BASE_URL", "http://127.0.0.1:11434");
        if (!model.equals(manifest.path("model").path("name").asText()) || !url.equals(manifest.path("endpoint").asText()))
            throw new IllegalStateException("Model/endpoint differ from frozen driver manifest");
        var client = ChatClient.builder(OpenAiChatModel.builder()
            .openAiApi(OpenAiApi.builder().baseUrl(url).apiKey("ollama").build())
            .defaultOptions(OpenAiChatOptions.builder().model(model).temperature(0.0).maxTokens(1536).reasoningEffort("none").build())
            .retryTemplate(RetryTemplate.builder().maxAttempts(1).build()).build()).build();
        Files.write(folder.resolve("dataset.json"), source);
        var conditions = JSON.createObjectNode().put("model", model).put("endpoint", url)
            .put("repeats", 3).put("expectedAnswers", 210).put("toolBudget", 12).put("timeoutSeconds", 90)
            .put("maxTokens", 1536).put("temperature", 0).put("reasoningEffort", "none")
            .put("armOrderPolicy", ORDER_POLICY).put("serialModelRequests", true)
            .put("primaryEvidence", "Exact delivered tool envelopes; rawWorldTrace is diagnostic")
            .put("scope", "Controlled legacy regression benchmark; not natural incident accuracy")
            .put("maxTokensScope", "Per completion, not total investigation tokens")
            .put("humanValidated", false);
        conditions.set("arms", JSON.valueToTree(ARMS));
        conditions.set("familyPhases", JSON.valueToTree(plan.phases()));
        conditions.set("familySizes", JSON.valueToTree(plan.sizes()));
        Files.writeString(folder.resolve("conditions.json"), conditions.toPrettyString());
        for (var scene : scenes) {
            try (var world = new NumericEvalWorld(scene)) {
                for (int rep = 0; rep < 3; rep++) {
                    var arms = orderedArms(plan, scene, rep);
                    for (int position = 0; position < arms.size(); position++) {
                        String arm = arms.get(position), answer = "", failure = "";
                        world.resetTrace(); long start = System.nanoTime();
                        var evidence = new HarnessComparisonRunner.DeliveredEvidence();
                        System.out.println("LEGACY_COMPARE_START " + scene.path("id").asText() + " " + arm + " " + rep);
                        try {
                            if (arm.equals("pi_plus"))
                                answer = HarnessComparisonRunner.pi(folder, model, url, world, scene, true, evidence);
                            else
                                answer = new FocusedInvestigator(client, 12, Duration.ofSeconds(90), Clock.fixed(world.evaluationTime, ZoneOffset.UTC))
                                    .investigate(HarnessComparisonRunner.prompt(scene, world), HarnessComparisonRunner.callbacks(world, true), evidence::record).conclusion();
                        } catch (Exception error) { failure = error.toString(); }
                        var row = JSON.createObjectNode().put("id", scene.path("id").asText())
                            .put("family", scene.path("family").asText()).put("split", "test").put("arm", arm)
                            .put("rep", rep).put("armPosition", position)
                            .put("familyOrdinal", plan.ordinals().get(scene.path("id").asText()))
                            .put("familyPhase", plan.phases().get(scene.path("family").asText()))
                            .put("sourceTier", scene.path("provenance").path("kind").asText())
                            .put("answer", answer == null ? "" : answer).put("error", failure)
                            .put("elapsedMs", (System.nanoTime()-start)/1_000_000);
                        row.set("trace", evidence.trace(true)); row.set("rawWorldTrace", world.trace());
                        Files.writeString(folder.resolve("results.jsonl"), JSON.writeValueAsString(row)+"\n", StandardOpenOption.CREATE, StandardOpenOption.APPEND);
                        System.out.println("LEGACY_COMPARE_DONE " + scene.path("id").asText() + " " + arm + " " + rep);
                    }
                }
            }
        }
        System.out.println("LEGACY_COMPARISON_COMPLETE " + folder.toAbsolutePath());
    }
}
