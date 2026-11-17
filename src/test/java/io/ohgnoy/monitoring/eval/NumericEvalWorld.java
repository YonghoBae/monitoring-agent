package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.ohgnoy.monitoring.application.agent.tools.AgentToolsFactory;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.loki.LokiQueryService;
import io.ohgnoy.monitoring.infrastructure.prometheus.AlertVerifier;
import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import io.ohgnoy.monitoring.infrastructure.prometheus.VerificationResult;
import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import org.springframework.ai.document.Document;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.http.client.support.HttpRequestWrapper;
import org.springframework.web.client.RestClient;

import java.io.*;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;
import java.util.regex.Pattern;

import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

/** Synthetic world, real PromQL; production service methods perform the queries. */
final class NumericEvalWorld implements AutoCloseable {
    private record FixtureLogLine(long offset, int index, String line) {}
    private static final ObjectMapper JSON = new ObjectMapper();
    // Replay formatting is explicit UTC rather than the host's mutable default zone.
    private static final DateTimeFormatter LOG_TIME = DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneOffset.UTC);
    private final JsonNode scenario;
    private final Process process;
    private final BufferedWriter commands;
    private final BufferedReader replies;
    private final ExecutorService reader = Executors.newSingleThreadExecutor(r -> { var t = new Thread(r, "fixture-replies"); t.setDaemon(true); return t; });
    private final ObjectNode trace = JSON.createObjectNode();
    final Instant evaluationTime;
    final String prometheusUrl;

    NumericEvalWorld(JsonNode scenario) throws Exception {
        this.scenario = scenario;
        trace.set("observations", JSON.createArrayNode()); trace.set("events", JSON.createArrayNode());
        process = new ProcessBuilder(System.getenv().getOrDefault("EVAL_NUMERIC_PYTHON", "python3"),
                Path.of("scripts", "numeric_fixture.py").toAbsolutePath().toString(), "--stdio")
                .redirectError(ProcessBuilder.Redirect.INHERIT).start();
        commands = process.outputWriter(StandardCharsets.UTF_8); replies = process.inputReader(StandardCharsets.UTF_8);
        try {
            commands.write(JSON.writeValueAsString(Map.of("action", "open", "scenario", scenario))); commands.newLine(); commands.flush();
            String line = reader.submit(replies::readLine).get(90, TimeUnit.SECONDS);
            JsonNode ready = JSON.readTree(line);
            if (!ready.path("status").asText().equals("ready")) throw new IllegalStateException("Fixture startup: " + ready);
            prometheusUrl = ready.path("prometheus_url").asText();
            evaluationTime = Instant.parse(ready.path("evaluation_time").asText());
        } catch (Exception e) { close(); throw e; }
    }

    synchronized ObjectNode trace() { return trace.deepCopy(); }
    synchronized void resetTrace() { trace.set("observations", JSON.createArrayNode()); trace.set("events", JSON.createArrayNode()); }
    private synchronized void observe(String source, String target, String status, Object data) {
        var observations = (ArrayNode) trace.get("observations");
        observations.addObject().put("id", "obs-" + (observations.size() + 1)).put("source", source)
                .put("target", target).put("status", status).set("data", JSON.valueToTree(data));
    }

    AgentToolsFactory toolsFactory() {
        var builder = RestClient.builder().requestInterceptor((request, body, execution) -> {
            URI logicalUri = logicalUri(request.getURI());
            var logical = new HttpRequestWrapper(request) { @Override public URI getURI() { return logicalUri; } };
            ClientHttpResponse raw = execution.execute(logical, body);
            byte[] bytes; HttpStatusCode status; HttpHeaders headers; String text;
            try { status = raw.getStatusCode(); headers = new HttpHeaders(); headers.putAll(raw.getHeaders()); text = raw.getStatusText(); bytes = raw.getBody().readAllBytes(); }
            finally { raw.close(); }
            try {
                JsonNode payload = JSON.readTree(bytes);
                String outcome = payload.path("status").asText().equals("success") ? "ok" : "invalid_argument";
                JsonNode data = payload.path("data");
                if (data.isObject() && data.path("result").isArray() && data.path("result").isEmpty()) outcome = "empty";
                // Discovery has match[] rather than query. Preserve its filter so a
                // reviewer cannot mistake a filtered list for the complete catalog.
                String discoveryTarget = logicalUri.getPath() + (logicalUri.getRawQuery() == null
                        ? "" : "?" + logicalUri.getRawQuery());
                observe("prometheus", parameter(logicalUri, "query", discoveryTarget), outcome, compact(payload));
            } catch (Exception e) { observe("prometheus", logicalUri.getPath(), "unavailable", "Invalid response"); }
            return new ClientHttpResponse() {
                public HttpStatusCode getStatusCode() { return status; }
                public String getStatusText() { return text; }
                public HttpHeaders getHeaders() { return headers; }
                public InputStream getBody() { return new ByteArrayInputStream(bytes); }
                public void close() { }
            };
        });
        var prometheus = new PrometheusQueryService(builder, prometheusUrl, JSON);
        var verifier = mock(AlertVerifier.class);
        when(verifier.verify(any(), any())).thenAnswer(inv -> {
            String name = inv.getArgument(0), labels = inv.getArgument(1);
            VerificationResult result = VerificationResult.unknown();
            if (scenario.path("alert").path("name").asText().equals(name)
                    && JSON.readTree(labels).equals(scenario.path("alert").path("labels"))) {
                JsonNode v = scenario.path("world").path("verify");
                result = switch (v.path("status").asText()) {
                    case "CONFIRMED" -> VerificationResult.confirmed(v.path("value").asText(), v.path("activeAt").asText(evaluationTime.toString()));
                    case "STALE" -> VerificationResult.stale();
                    default -> VerificationResult.unknown();
                };
            }
            observe("verify_alert", name, result.status() == VerificationResult.Status.UNKNOWN ? "unavailable" : "ok", result.toPromptLine());
            return result;
        });
        var loki = mock(LokiQueryService.class);
        when(loki.queryRecentLogs(anyString(), any(), any(), anyInt())).thenAnswer(inv -> {
            String expr = inv.getArgument(0); int limit = inv.getArgument(3);
            Instant start = inv.getArgument(1), end = inv.getArgument(2);
            long seconds = Duration.between(start, end).toSeconds();
            var match = Pattern.compile("\\{job=\"docker\"}\\s*\\|=\\s*`([A-Za-z0-9_.-]+)`").matcher(expr);
            var fileMatch = Pattern.compile("\\{job=\"docker\",filename=\"/fixture/docker/([A-Za-z0-9_.-]+)/container.log\"}").matcher(expr);
            boolean byFilename=fileMatch.matches(), byContent=match.matches();
            if ((!byFilename&&!byContent) || seconds <= 0 || limit < 1) throw new IllegalArgumentException("Unsupported log source/query");
            String target = byFilename?fileMatch.group(1):match.group(1);
            List<FixtureLogLine> candidates = new ArrayList<>();
            int index = 0;
            for (JsonNode log : scenario.path("world").path("logs")) {
                if (!log.path("source").asText().equals("docker") || !log.path("name").asText().equals(target)) continue;
                for (JsonNode entry : log.path("entries")) {
                    long offset = entry.path("offset_seconds").asLong(); String line = entry.path("line").asText();
                    if (offset >= -seconds && offset <= 0 && (byFilename||line.contains(target)))
                        candidates.add(new FixtureLogLine(offset,index,line));
                    index++;
                }
            }
            // LokiQueryService requests direction=backward with the limit, then
            // sorts the selected results chronologically for display. Select
            // newest first before limiting; never prefer an incident-specific line.
            candidates.sort(Comparator.comparingLong(FixtureLogLine::offset)
                    .thenComparingInt(FixtureLogLine::index).reversed());
            List<FixtureLogLine> selected = new ArrayList<>(candidates.subList(0,Math.min(limit,candidates.size())));
            selected.sort(Comparator.comparingLong(FixtureLogLine::offset));
            List<String> lines = selected.stream().map(entry -> {
                String text=entry.line().length()>300?entry.line().substring(0,300)+"...":entry.line();
                return "["+LOG_TIME.format(evaluationTime.plusSeconds(entry.offset()))+"] "+text;
            }).toList();
            observe("log:docker:" + target, target, lines.isEmpty() ? "empty" : "ok", lines);
            return lines;
        });
        var rag = mock(AlertVectorService.class);
        when(rag.searchSimilar(anyString(), anyInt())).thenAnswer(inv -> {
            String query = inv.getArgument(0); int k = inv.getArgument(1);
            if (query.isBlank() || k < 1) throw new IllegalArgumentException("Invalid KB query");
            List<Document> documents = new ArrayList<>();
            for (JsonNode doc : scenario.path("world").path("rag")) {
                if (documents.size() == k) break;
                documents.add(new Document(doc.path("text").asText(), Map.of("type", doc.path("type").asText("analysis"), "outcome", doc.path("outcome").asText())));
            }
            observe("rag", query, documents.isEmpty() ? "empty" : "ok", documents.stream().map(Document::getText).toList());
            return documents;
        });
        var command = mock(CommandExecutorService.class);
        when(command.containerLogPath(anyString())).thenAnswer(inv -> {
            String name=inv.getArgument(0);
            boolean exists=false;
            for(JsonNode item:scenario.path("world").path("containers"))if(item.asText().equals(name))exists=true;
            for(JsonNode item:scenario.path("world").path("logs"))if(item.path("source").asText().equals("docker")&&item.path("name").asText().equals(name))exists=true;
            if(!exists)throw new IllegalStateException("Container log path unavailable");
            return "/fixture/docker/"+name+"/container.log";
        });
        when(command.inspectContainer(anyString())).thenAnswer(inv -> {
            String name=inv.getArgument(0);JsonNode details=scenario.path("world").path("container_details").path(name);
            if(details.isMissingNode()){observe("docker_inspect",name,"unavailable","No details provided in this world");throw new IllegalStateException("Container details unavailable in fixture");}
            observe("docker_inspect",name,"ok",details);return details.toString();
        });
        when(command.listContainers()).thenAnswer(inv -> {
            if (scenario.path("world").path("inventory_status").asText().equals("unavailable")) {
                observe("docker_inventory", "containers", "unavailable", "Docker API unavailable");
                throw new IllegalStateException("Docker API unavailable");
            }
            List<String> names = new ArrayList<>(); scenario.path("world").path("containers").forEach(n -> names.add(n.asText()));
            observe("docker_inventory", "containers", "ok", names); return names;
        });
        when(command.execute(anyString())).thenAnswer(inv -> {
            synchronized (this) { ((ArrayNode) trace.get("events")).addObject().put("type", "mutation_attempt").put("command", (String) inv.getArgument(0)); }
            throw new IllegalStateException("Mutation is not provided by this benchmark");
        });
        return new AgentToolsFactory(verifier, prometheus, loki, rag, command);
    }

    private URI logicalUri(URI uri) {
        String value = uri.toString();
        if (uri.getPath().equals("/api/v1/query")) value += "&time=" + evaluationTime.getEpochSecond();
        else if (uri.getPath().equals("/api/v1/query_range")) {
            long from = Long.parseLong(parameter(uri, "start", "0")), to = Long.parseLong(parameter(uri, "end", "0"));
            value = value.replaceAll("(?<=[?&])start=[^&]*", "start=" + (evaluationTime.getEpochSecond() - (to - from)))
                    .replaceAll("(?<=[?&])end=[^&]*", "end=" + evaluationTime.getEpochSecond());
        }
        return URI.create(value);
    }
    private static String parameter(URI uri, String name, String fallback) {
        for (String p : Objects.requireNonNullElse(uri.getRawQuery(), "").split("&")) {
            String[] pair = p.split("=", 2);
            if (pair[0].equals(name) && pair.length == 2) return URLDecoder.decode(pair[1], StandardCharsets.UTF_8);
        }
        return fallback;
    }
    private static JsonNode compact(JsonNode root) {
        JsonNode copy = root.deepCopy();
        for (JsonNode series : copy.path("data").path("result")) {
            JsonNode values = series.path("values");
            if (values.isArray() && values.size() > 4) {
                ArrayNode small = JSON.createArrayNode(); small.add(values.get(0)); small.add(values.get(values.size() / 2)); small.add(values.get(values.size() - 1));
                ((ObjectNode) series).set("values", small); ((ObjectNode) series).put("sample_count", values.size());
            }
        }
        return copy;
    }
    @Override public void close() {
        try { commands.write("{\"action\":\"close\"}"); commands.newLine(); commands.flush(); commands.close(); }
        catch (Exception ignored) { }
        try { if (!process.waitFor(20, TimeUnit.SECONDS)) { process.destroy(); if (!process.waitFor(10, TimeUnit.SECONDS)) process.destroyForcibly(); } }
        catch (InterruptedException e) { process.destroy(); Thread.currentThread().interrupt(); }
        reader.shutdownNow();
    }
}
