package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import io.ohgnoy.monitoring.application.agent.AgentExecution;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.function.Executable;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.ai.tool.ToolCallback;

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
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Pattern;

import static io.ohgnoy.monitoring.eval.HarnessComparisonRunner.JSON;
import static org.assertj.core.api.Assertions.*;
import static org.junit.jupiter.api.Assertions.assertAll;

/** Additional semantic exposure checks; preserves the separate 35-case replay evidence. */
@Tag("eval")
@EnabledIfEnvironmentVariable(named="RUN_LEGACY_SEMANTIC_BOUNDARY_TESTS",matches="1")
class LegacySemanticBoundaryTest {
    private static final Path DATASET=Path.of("eval/v4/dataset.json");
    private static final Path REPORT=Path.of("build/eval/legacy-semantic-boundary-"+System.currentTimeMillis());

    @ParameterizedTest(name="semantic boundary {0}")
    @ValueSource(strings={"host_oom_killer","inventory_unavailable","docker_target_port_mismatch","docker_target_port_correct"})
    @Timeout(120)
    void onlyProvidedToolEvidenceEstablishesTheRequestedResult(String identifier)throws Exception {
        byte[] original=Files.readAllBytes(DATASET);
        JsonNode selected=null;
        for(var scene:JSON.readTree(original).path("scenarios"))if(scene.path("id").asText().equals(identifier))selected=scene;
        assertThat(selected).isNotNull();
        var report=JSON.createObjectNode().put("id",identifier).put("source_dataset_sha256",sha256(original))
            .put("model_calls",0).put("scope","Exact enhanced-tool exposure, not model reasoning or live Pi transport");
        var evidence=new HarnessComparisonRunner.DeliveredEvidence();
        var checks=new ArrayList<Executable>();
        Files.createDirectories(REPORT);
        try(var world=new NumericEvalWorld(selected)) {
            ToolCallback[] first=HarnessComparisonRunner.callbacks(world,true);
            ToolCallback[] second=HarnessComparisonRunner.callbacks(world,true);
            Map<String,String> definitions=definitions(first);
            report.set("shared_enhanced_callback_definitions",JSON.valueToTree(definitions));
            report.put("independent_factory_descriptor_sets_equal",definitions.equals(definitions(second)));
            checks.add(()->assertThat(definitions).isEqualTo(definitions(second)));
            checks.add(()->assertThat(definitions.keySet()).doesNotContain("execute_command","read_host_logs","read_kernel_logs"));
            var execution=new AgentExecution(12,Duration.ofSeconds(90),Clock.systemUTC(),
                Clock.fixed(world.evaluationTime,ZoneOffset.UTC),evidence::record);
            var callbacks=new LinkedHashMap<String,ToolCallback>();
            Arrays.stream(first).forEach(callback->callbacks.put(callback.getToolDefinition().name(),execution.wrap(callback)));
            JsonNode inventory=call(callbacks,"get_containers",Map.of());

            if(identifier.equals("host_oom_killer")) {
                String hiddenLine=null;
                for(var log:selected.path("world").path("logs"))
                    if(log.path("source").asText().equals("host")&&log.path("name").asText().equals("kernel"))
                        hiddenLine=log.path("entries").get(0).path("line").asText();
                assertThat(hiddenLine).contains("Killed process");
                report.put("withheld_host_line_sha256",sha256(hiddenLine.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
                JsonNode contentRoute=call(callbacks,"query_loki",Map.of("containerName","kernel","timeRangeMinutes","30"));
                JsonNode pathRoute=call(callbacks,"read_container_logs",Map.of("containerName","kernel","minutes",30));
                JsonNode dockerLog=call(callbacks,"read_container_logs",Map.of("containerName","ollama","minutes",30));
                JsonNode metric=call(callbacks,"query_prometheus",Map.of("promql","increase(node_vmstat_oom_kill[30m])","timeRangeMinutes","30"));
                JsonNode rag=call(callbacks,"search_rag",Map.of("query","kernel OOM victim killed process"));
                report.put("content_log_route_status",contentRoute.path("status").asText())
                    .put("path_log_route_status",pathRoute.path("status").asText())
                    .put("docker_model_load_reachable",dockerLog.path("data").asText().contains("loading model"))
                    .put("oom_counter_reachable",metric.path("data").asText().contains("현재="));
                String outputs=evidence.trace(true).path("observations").toString();
                boolean hiddenReturned=outputs.contains("Killed process")||outputs.contains("88412");
                report.put("host_victim_evidence_returned",hiddenReturned);
                checks.add(()->assertThat(hiddenReturned).isFalse());
                checks.add(()->assertThat(contentRoute.path("status").asText()).isIn("invalid_argument","empty","unavailable"));
                checks.add(()->assertThat(pathRoute.path("status").asText()).isEqualTo("unavailable"));
                checks.add(()->assertThat(dockerLog.path("status").asText()).isEqualTo("ok"));
                checks.add(()->assertThat(dockerLog.path("data").asText()).contains("loading model").doesNotContain("Killed process","88412"));
                checks.add(()->assertThat(metric.path("status").asText()).isEqualTo("ok"));
                checks.add(()->assertThat(metric.path("data").asText()).contains("현재="));
                checks.add(()->assertThat(rag.path("status").asText()).isEqualTo("empty"));
                report.put("interpretation","OOM counter and Docker model-load log are reachable, but neither identifies a kernel-selected victim. Both supplied log routes with kernel target withhold the source=host diagnostic.");
            }else if(identifier.equals("inventory_unavailable")) {
                report.put("inventory_status",inventory.path("status").asText())
                    .put("inventory_data",inventory.path("data").asText());
                checks.add(()->assertThat(inventory.path("status").asText()).isEqualTo("unavailable"));
                checks.add(()->assertThat(inventory.path("data").asText()).doesNotContain("실행 중인 컨테이너 없음","[]"));
                report.put("interpretation","Inventory retrieval failed; the fixture's internal empty container list is not delivered as a counted normal-empty inventory.");
            }else {
                JsonNode inspection=call(callbacks,"inspect_container",Map.of("containerName","web-app"));
                JsonNode logs=call(callbacks,"read_container_logs",Map.of("containerName","web-app","minutes",30));
                JsonNode details=JSON.readTree(inspection.path("data").asText());
                String expectedDestination=identifier.equals("docker_target_port_mismatch")?"8081/tcp":"8080/tcp";
                var listener=Pattern.compile("server listening on 0\\.0\\.0\\.0:([0-9]+)").matcher(logs.path("data").asText());
                boolean listenerFound=listener.find();
                String listenerPort=listenerFound?listener.group(1):"";
                String mappedHostPort=details.path("ports").path(expectedDestination).path(0).path("HostPort").asText();
                boolean matches=expectedDestination.equals(listenerPort+"/tcp");
                report.put("delivered_host_port",mappedHostPort).put("delivered_container_destination",expectedDestination)
                    .put("delivered_listener_port",listenerPort).put("ports_match",matches);
                checks.add(()->assertThat(inventory.path("data").asText()).contains("web-app"));
                checks.add(()->assertThat(inspection.path("status").asText()).isEqualTo("ok"));
                checks.add(()->assertThat(logs.path("status").asText()).isEqualTo("ok"));
                checks.add(()->assertThat(mappedHostPort).isEqualTo("9010"));
                checks.add(()->assertThat(listenerPort).isEqualTo("8080"));
                checks.add(()->assertThat(matches).isEqualTo(identifier.equals("docker_target_port_correct")));
                report.put("interpretation","The Docker host binding and separately delivered application listener jointly establish the mapping comparison; neither source is replaced by gold metadata.");
            }
            for(var observation:evidence.trace(true).path("observations")) {
                JsonNode envelope=JSON.readTree(observation.path("output").asText());
                var keys=new java.util.HashSet<String>();envelope.fieldNames().forEachRemaining(keys::add);
                checks.add(()->assertThat(keys).isEqualTo(Set.of("data","observed_at","source","status")));
                checks.add(()->assertThat(envelope.path("observed_at").asText()).isEqualTo(world.evaluationTime.toString()));
                checks.add(()->assertThat(observation.path("output").asText()).doesNotContain("\"gold\"","\"family\"","\"phase\"",identifier));
            }
            checks.add(()->assertThat(world.trace().path("events")).isEmpty());
            report.set("trace",evidence.trace(true));
            report.set("rawWorldTrace",world.trace());
        }catch(Exception failure) {
            report.put("execution_error",failure.toString());throw failure;
        }finally {
            Files.writeString(REPORT.resolve(identifier+".json"),JSON.writerWithDefaultPrettyPrinter().writeValueAsString(report)+"\n");
        }
        checks.add(()->assertThat(Files.readAllBytes(DATASET)).containsExactly(original));
        System.out.println("LEGACY_SEMANTIC_BOUNDARY "+identifier+" model_calls=0 report="+REPORT.resolve(identifier+".json"));
        assertAll(identifier,checks);
    }

    private static JsonNode call(Map<String,ToolCallback> callbacks,String name,Map<String,?> input)throws Exception {
        return JSON.readTree(callbacks.get(name).call(JSON.writeValueAsString(input)));
    }
    private static Map<String,String> definitions(ToolCallback[] callbacks) {
        var result=new TreeMap<String,String>();
        for(var callback:callbacks) {
            var definition=callback.getToolDefinition();
            result.put(definition.name(),definition.description()+"\n"+definition.inputSchema());
        }
        return result;
    }
    private static String sha256(byte[] bytes)throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
}
