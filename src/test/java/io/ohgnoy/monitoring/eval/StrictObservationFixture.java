package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

/** Real AST validation for legacy summaries; unsupported computations are ungraded. */
final class StrictObservationFixture {
    private final ObjectMapper mapper = new ObjectMapper();
    private final JsonNode scenario;
    private final List<String> unsupported = new ArrayList<>();
    private final Instant observedAt = Instant.now();
    private final List<String> knownContainers;
    StrictObservationFixture(JsonNode scenario) { this(scenario, List.of()); }
    StrictObservationFixture(JsonNode scenario, List<String> containers) {
        this.scenario = scenario;
        this.knownContainers = List.copyOf(containers);
        invoke(Map.of("action", "preflight"));
    }

    List<String> logs(String expression, Instant start, Instant end, int limit) {
        if (start == null || end == null || !start.isBefore(end) || limit < 1) throw new IllegalArgumentException("Invalid log query bounds");
        if (end.isBefore(observedAt) || start.isAfter(observedAt)) return List.of();
        var match = Pattern.compile("\\{job=\"docker\"}\\s*\\|=\\s*`([A-Za-z0-9_.-]+)`").matcher(expression);
        if (!match.matches()) { unsupported("LogQL source/grammar: " + expression); return List.of(); }
        String target = match.group(1);
        if (!knownContainers.contains(target)) { unsupported("Log source inventory missing: " + target); return List.of(); }
        for (JsonNode entry : scenario.path("mocks").path("loki")) {
            if (entry.path("keyword").asText().equals(target)) {
                List<String> lines = new ArrayList<>();
                for (JsonNode line : entry.path("lines")) { if (lines.size() == limit) break; lines.add(line.asText()); }
                return lines;
            }
        }
        return List.of();
    }

    private void unsupported(String reason) { synchronized (unsupported) { unsupported.add(reason); } }

    String query(String expression, Instant start, Instant end) {
        if (start == null || end == null || !start.isBefore(end)) return "잘못된 조회 시간 범위";
        if (end.isBefore(observedAt) || start.isAfter(observedAt)) return "데이터 없음: fixture 관측 시각 밖의 조회";
        JsonNode r = invoke(Map.of("scenario", scenario, "query", expression));
        return switch (r.path("status").asText()) {
            case "invalid_argument" -> "잘못된 PromQL: " + r.path("data").asText();
            case "empty" -> "데이터 없음: " + r.path("data").asText();
            case "unsupported_fixture" -> {
                synchronized (unsupported) { unsupported.add(expression + ": " + r.path("data").asText()); }
                yield "EVAL_UNSUPPORTED_FIXTURE: " + r.path("data").asText();
            }
            case "observation" -> r.path("data").asText();
            default -> throw new IllegalStateException("Unknown fixture response");
        };
    }
    JsonNode verify(String name, String labels) {
        try { return invoke(Map.of("action", "verify", "scenario", scenario, "name", name, "labels", mapper.readTree(labels))); }
        catch (com.fasterxml.jackson.core.JsonProcessingException e) { return mapper.createObjectNode().put("status", "UNKNOWN"); }
    }
    boolean hasUnsupportedQueries() { synchronized (unsupported) { return !unsupported.isEmpty(); } }
    List<String> unsupportedQueries() { synchronized (unsupported) { return List.copyOf(unsupported); } }
    private JsonNode invoke(Map<String, ?> request) {
        Process process = null;
        try {
            process = new ProcessBuilder(System.getenv().getOrDefault("EVAL_PROMQL_PYTHON", "python3"),
                    Path.of("scripts", "eval_fixture.py").toAbsolutePath().toString()).start();
            try (var input = process.getOutputStream()) { mapper.writeValue(input, request); }
            if (!process.waitFor(10, TimeUnit.SECONDS)) throw new IllegalStateException("Fixture parser timeout");
            if (process.exitValue() != 0) throw new IllegalStateException(new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8));
            return mapper.readTree(process.getInputStream());
        } catch (Exception e) {
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            throw new IllegalStateException("Evaluation parser unavailable: install scripts/requirements-eval.txt; set EVAL_PROMQL_PYTHON", e);
        } finally { if (process != null && process.isAlive()) process.destroyForcibly(); }
    }
}
