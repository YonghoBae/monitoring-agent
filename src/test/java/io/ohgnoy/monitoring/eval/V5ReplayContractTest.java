package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.ohgnoy.monitoring.application.agent.AgentExecution;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.ai.tool.ToolCallback;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Duration;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import static io.ohgnoy.monitoring.eval.HarnessComparisonRunner.JSON;
import static org.assertj.core.api.Assertions.*;
import static org.junit.jupiter.api.Assertions.assertAll;

/** Real isolated Prometheus fixture and production callbacks, with no model calls. */
@Tag("eval")
@EnabledIfEnvironmentVariable(named="RUN_V5_REPLAY_TESTS",matches="1")
class V5ReplayContractTest {
    private static final Path DATASET=Path.of("eval/v5/dataset.json");
    private static final Path GOLD=Path.of("eval/v5/gold.json");

    static List<String> caseIds()throws Exception {
        var cases=new ArrayList<String>();
        JSON.readTree(Files.readString(DATASET)).path("scenarios").forEach(scene->cases.add(scene.path("id").asText()));
        assertThat(cases).hasSize(8).doesNotHaveDuplicates();
        return cases;
    }

    @ParameterizedTest(name="replay {0}")
    @MethodSource("caseIds")
    @Timeout(120)
    void frozenCaseIsReachableWithoutMetadataLeakage(String id)throws Exception {
        byte[] datasetBytes=Files.readAllBytes(DATASET);
        String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(datasetBytes));
        JsonNode scene=null;
        for(var candidate:JSON.readTree(datasetBytes).path("scenarios"))if(candidate.path("id").asText().equals(id))scene=candidate;
        assertThat(scene).isNotNull();
        JsonNode selected=scene;
        JsonNode gold=JSON.readTree(Files.readString(GOLD)).path(id);
        JsonNode provenance=JSON.readTree(Files.readString(Path.of("eval/v5/provenance.json"))).path(id);
        System.out.println("V5_REPLAY_START "+id+" dataset_sha256="+hash+" model_calls=0");
        try(var world=new NumericEvalWorld(selected)) {
            String prompt=HarnessComparisonRunner.prompt(selected,world);
            ObjectNode altered=selected.deepCopy();
            for(String key:List.of("id","family","phase","source","original_id","hidden_original_id","source_phase_event_ids"))
                altered.put(key,"PRIVATE_METADATA_CANARY_"+key);
            var evidence=new HarnessComparisonRunner.DeliveredEvidence();
            var execution=new AgentExecution(12,Duration.ofSeconds(90),Clock.systemUTC(),
                Clock.fixed(world.evaluationTime,ZoneOffset.UTC),evidence::record);
            Map<String,ToolCallback> callbacks=Arrays.stream(HarnessComparisonRunner.callbacks(world,true))
                .collect(Collectors.toMap(callback->callback.getToolDefinition().name(),Function.identity()));
            assertThat(callbacks).containsKeys("get_containers","read_container_logs");
            String inventory=execution.wrap(callbacks.get("get_containers")).call("{}");
            String returned=execution.wrap(callbacks.get("read_container_logs"))
                .call("{\"containerName\":\"service-db\",\"minutes\":30}");
            JsonNode envelope=JSON.readTree(returned);
            String data=envelope.path("data").asText();
            var sourceLines=new ArrayList<String>();
            var logTime=DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneOffset.UTC);
            for(var log:selected.path("world").path("logs"))for(var entry:log.path("entries")) {
                String sourceLine=entry.path("line").asText();
                if(sourceLine.length()>300)sourceLine=sourceLine.substring(0,300)+"...";
                sourceLines.add("["+logTime.format(world.evaluationTime.plusSeconds(entry.path("offset_seconds").asLong()))+"] "+sourceLine);
            }
            List<String> delivered=data.lines().toList();
            String required=requiredDiagnostic(selected,gold);
            boolean reached=data.contains(required);
            System.out.println("V5_REPLAY "+id+" dataset_sha256="+hash+" source_lines="+sourceLines.size()
                +" delivered_lines="+delivered.size()+" discriminator_reached="+reached+" model_calls=0");
            assertAll(id,
                ()->assertThat(prompt).contains(selected.path("question").asText()).doesNotContain(id,selected.path("family").asText(),"PRIVATE_METADATA_CANARY"),
                ()->{
                    assertThat(prompt).doesNotContain(provenance.path("source").asText(),provenance.path("phase").asText());
                    for(var eventId:provenance.path("source_phase_event_ids"))assertThat(prompt).doesNotContain(eventId.asText());
                },
                ()->assertThat(HarnessComparisonRunner.prompt(altered,world)).isEqualTo(prompt),
                ()->assertThat(JSON.readTree(inventory).path("data").asText()).contains("service-db"),
                ()->assertThat(envelope.path("status").asText()).isEqualTo("ok"),
                ()->assertThat(delivered).isNotEmpty().hasSizeLessThanOrEqualTo(30).allSatisfy(line->assertThat(sourceLines).contains(line)),
                ()->assertThat(data).as("Discriminating captured evidence must be reachable through the real log callback").contains(required),
                ()->assertSuccessfulRowCheck(selected,gold,data),
                ()->{if(gold.path("direct_cause").asText().equals("unknown"))assertThat(data).doesNotContain("server version mismatch","Permission denied");},
                ()->assertThat(evidence.trace(true).path("observations").get(1).path("output").asText()).isEqualTo(returned),
                ()->assertThat(world.trace().path("events")).isEmpty());
        }
    }

    private static String requiredDiagnostic(JsonNode scene,JsonNode gold) {
        if(gold.path("direct_cause").asText().equals("unknown"))return "Detailed output is unavailable in this view.";
        if(gold.path("expected_status").asText().equals("failed"))
            return scene.path("family").asText().equals("pg_dump_version")?"aborting because of server version mismatch":"/docker-entrypoint-initdb.d/00-eval.sql: Permission denied";
        return scene.path("family").asText().equals("pg_dump_version")?"SELECT count(*),sum(value) FROM restored eval_marker":"SELECT count(*) FROM eval_marker";
    }

    private static void assertSuccessfulRowCheck(JsonNode scene,JsonNode gold,String data) {
        if(!gold.path("expected_status").asText().equals("succeeded"))return;
        assertThat(data).contains("\"exit_code\": 0");
        if(scene.path("family").asText().equals("pg_dump_version"))assertThat(data).contains("3:60","\"operation\": \"pg_dump\"");
        else assertThat(data).contains("\"stdout\": \"3");
    }
}
