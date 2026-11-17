package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.ohgnoy.monitoring.application.agent.AgentExecution;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.function.Executable;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.ai.tool.ToolCallback;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Duration;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import static io.ohgnoy.monitoring.eval.HarnessComparisonRunner.JSON;
import static org.assertj.core.api.Assertions.*;
import static org.junit.jupiter.api.Assertions.assertAll;

/** Model-free, real-fixture checks of delivered tool evidence, never raw-data grading. */
@Tag("eval")
@EnabledIfEnvironmentVariable(named="RUN_LEGACY_REPLAY_TESTS",matches="1")
class LegacyReplayContractTest {
    private static final Path DATASET=Path.of("eval/v4/dataset.json");
    private static final Path REPORT=Path.of(System.getenv().getOrDefault("EVAL_LEGACY_PREFLIGHT_OUT",
        "build/eval/legacy-replay-preflight-"+System.currentTimeMillis()));
    private static final Pattern CURRENT=Pattern.compile("현재=([+-]?(?:[0-9]+(?:\\.[0-9]+)?|\\.[0-9]+)(?:[Ee][+-]?[0-9]+)?)");
    private static final Pattern SAMPLE_TIME=Pattern.compile("표본시각=([0-9]+(?:\\.[0-9]+)?)");

    static List<String> cases()throws Exception {
        var identifiers=new ArrayList<String>();
        int expressions=0,witnesses=0;
        for(var scene:JSON.readTree(Files.readAllBytes(DATASET)).path("scenarios")) {
            if(!scene.path("split").asText().equals("test"))continue;
            identifiers.add(scene.path("id").asText());
            for(var gold:scene.path("gold")) {
                if(gold.path("validation_expr").isTextual())expressions++;
                if(gold.path("validation_log_substring").isTextual())witnesses++;
            }
        }
        assertThat(identifiers).hasSize(35).doesNotHaveDuplicates();
        assertThat(expressions).isEqualTo(34);
        assertThat(witnesses).isEqualTo(1);
        return identifiers;
    }

    @ParameterizedTest(name="legacy replay {0}")
    @MethodSource("cases")
    @Timeout(120)
    void deliveredEvidenceReachesLegacyNumericTargetsAndLogWitnesses(String identifier)throws Exception {
        byte[] original=Files.readAllBytes(DATASET);
        String datasetHash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(original));
        JsonNode scene=null;
        for(var candidate:JSON.readTree(original).path("scenarios"))if(candidate.path("id").asText().equals(identifier))scene=candidate;
        assertThat(scene).isNotNull();
        var report=JSON.createObjectNode().put("id",identifier).put("dataset_sha256",datasetHash).put("model_calls",0);
        var numeric=report.putArray("numeric_checks");
        var logs=report.putArray("log_source_checks");
        var checks=new ArrayList<Executable>();
        var evidence=new HarnessComparisonRunner.DeliveredEvidence();
        Files.createDirectories(REPORT);
        System.out.println("LEGACY_REPLAY_START "+identifier+" model_calls=0");
        try(var world=new NumericEvalWorld(scene)) {
            var execution=new AgentExecution(12,Duration.ofSeconds(90),Clock.systemUTC(),
                Clock.fixed(world.evaluationTime,ZoneOffset.UTC),evidence::record);
            Map<String,ToolCallback> callbacks=new LinkedHashMap<>();
            Arrays.stream(HarnessComparisonRunner.callbacks(world,true))
                .forEach(callback->callbacks.put(callback.getToolDefinition().name(),execution.wrap(callback)));
            assertThat(callbacks).containsKeys("get_containers","list_metrics","query_prometheus","read_container_logs");
            callbacks.get("get_containers").call("{}");
            callbacks.get("list_metrics").call("{\"filter\":\"\"}");

            for(var gold:scene.path("gold")) {
                if(!gold.path("validation_expr").isTextual())continue;
                String expression=gold.path("validation_expr").asText();
                String input=JSON.writeValueAsString(Map.of("promql",expression,"timeRangeMinutes","30"));
                String response=callbacks.get("query_prometheus").call(input);
                var envelope=JSON.readTree(response);
                String delivered=envelope.path("data").asText();
                var values=new ArrayList<BigDecimal>();
                var matcher=CURRENT.matcher(delivered);
                while(matcher.find())values.add(new BigDecimal(matcher.group(1)));
                var times=new ArrayList<BigDecimal>();
                matcher=SAMPLE_TIME.matcher(delivered);
                while(matcher.find())times.add(new BigDecimal(matcher.group(1)));
                BigDecimal expected=new BigDecimal(gold.path("value").asText());
                BigDecimal tolerance=new BigDecimal(gold.path("tolerance").asText("0"));
                boolean precise=values.size()==1&&values.getFirst().subtract(expected).abs().compareTo(tolerance)<=0;
                String assessment=values.isEmpty()?"blocked_no_delivered_scalar":values.size()>1?"blocked_multiple_series_need_entity_selection":precise?"pass":"blocked_delivered_precision_or_value";
                var item=numeric.addObject().put("key",gold.path("key").asText()).put("expression",expression)
                    .put("expected",expected.toPlainString()).put("absolute_tolerance",tolerance.toPlainString())
                    .put("assessment",assessment).put("delivered_envelope",response);
                item.set("delivered_current_values",JSON.valueToTree(values.stream().map(BigDecimal::toPlainString).toList()));
                if(values.size()==1)item.put("absolute_difference",values.getFirst().subtract(expected).abs().toPlainString());
                checks.add(()->assertThat(envelope.path("status").asText()).as(expression).isEqualTo("ok"));
                checks.add(()->assertThat(envelope.path("observed_at").asText()).isEqualTo(world.evaluationTime.toString()));
                checks.add(()->assertThat(values).as("A delivered scalar is required; raw backend values are not substituted: "+expression).hasSize(1));
                checks.add(()->assertThat(precise).as("Delivered value must meet frozen gold absolute tolerance: "+expression).isTrue());
                checks.add(()->assertThat(times).as("Delivered sample time, not only envelope time").hasSize(1)
                    .allSatisfy(time->assertThat(time.compareTo(BigDecimal.valueOf(world.evaluationTime.getEpochSecond()))).isZero()));
            }

            var targets=new LinkedHashSet<String>();
            for(var gold:scene.path("gold"))for(var target:gold.path("evidence_targets"))
                if(target.asText().startsWith("log:docker:"))targets.add(target.asText().substring("log:docker:".length()));
            for(String target:targets) {
                String input=JSON.writeValueAsString(Map.of("containerName",target,"minutes",30));
                String response=callbacks.get("read_container_logs").call(input);
                var envelope=JSON.readTree(response);
                String delivered=envelope.path("data").asText();
                var missing=new ArrayList<String>();
                var outsideWindow=new ArrayList<String>();
                var longLines=new ArrayList<String>();
                int sourceCount=0;
                for(var log:scene.path("world").path("logs")) {
                    if(!log.path("source").asText().equals("docker")||!log.path("name").asText().equals(target))continue;
                    for(var entry:log.path("entries")) {
                        sourceCount++;
                        String line=entry.path("line").asText();
                        long offset=entry.path("offset_seconds").asLong();
                        if(offset < -1800||offset>0)outsideWindow.add(line);
                        if(line.length()>300)longLines.add(line);
                        if(!delivered.contains(line))missing.add(line);
                    }
                }
                var item=logs.addObject().put("source","log:docker:"+target).put("window_minutes",30)
                    .put("source_lines",sourceCount).put("delivered_lines",delivered.lines().count())
                    .put("full_source_retained",missing.isEmpty()).put("delivered_envelope",response);
                item.set("not_delivered_full_source_lines",JSON.valueToTree(missing));
                item.set("source_lines_outside_window",JSON.valueToTree(outsideWindow));
                item.set("source_lines_over_300_chars",JSON.valueToTree(longLines));
                checks.add(()->assertThat(envelope.path("status").asText()).as(target).isEqualTo("ok"));
                checks.add(()->assertThat(delivered.lines().count()).isLessThanOrEqualTo(30));
                checks.add(()->assertThat(missing).as("Any gold-source line lost to selection, window or truncation must be reported: "+target).isEmpty());
                for(var gold:scene.path("gold")) {
                    if(!gold.path("validation_log_substring").isTextual())continue;
                    boolean matches=false;
                    for(var evidenceTarget:gold.path("evidence_targets"))if(evidenceTarget.asText().equals("log:docker:"+target))matches=true;
                    if(!matches)continue;
                    String witness=gold.path("validation_log_substring").asText();
                    item.put("numeric_witness",witness).put("numeric_witness_reached",delivered.contains(witness));
                    String shortResponse=callbacks.get("read_container_logs").call(JSON.writeValueAsString(Map.of("containerName",target,"minutes",1)));
                    String shortData=JSON.readTree(shortResponse).path("data").asText();
                    item.put("one_minute_control_envelope",shortResponse).put("one_minute_control_excludes_witness",!shortData.contains(witness));
                    checks.add(()->assertThat(delivered).contains(witness));
                    checks.add(()->assertThat(witness).contains(gold.path("value").asText()));
                    checks.add(()->assertThat(shortData).as("The historical witness must not leak into an excluding window").doesNotContain(witness));
                }
            }
            checks.add(()->assertThat(world.trace().path("events")).isEmpty());
            report.set("trace",evidence.trace(true));
            report.set("rawWorldTrace",world.trace());
            report.put("scope","Numeric validation expressions and log-source reachability only; other categorical fields are not certified by this test.");
        }catch(Exception failure) {
            report.put("setup_or_execution_error",failure.toString());
            throw failure;
        }finally {
            Files.writeString(REPORT.resolve(identifier+".json"),JSON.writerWithDefaultPrettyPrinter().writeValueAsString(report)+"\n");
        }
        checks.add(()->assertThat(Files.readAllBytes(DATASET)).as("Frozen source data must remain unchanged").containsExactly(original));
        System.out.println("LEGACY_REPLAY_DONE "+identifier+" numeric="+numeric.size()+" log_sources="+logs.size()+" report="+REPORT.resolve(identifier+".json"));
        assertAll(identifier,checks);
    }
}
