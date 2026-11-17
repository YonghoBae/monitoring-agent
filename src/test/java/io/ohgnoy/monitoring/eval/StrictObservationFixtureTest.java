package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import java.time.Instant;
import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "EVAL_PROMQL_PYTHON", matches = ".+")
class StrictObservationFixtureTest {
    @Test
    void actualDatasetRejectsWrongQueriesWithoutLlmCalls() throws Exception {
        var mapper = new ObjectMapper(new YAMLFactory());
        var root = mapper.readTree(getClass().getResourceAsStream("/eval-dataset-v2.yml"));
        var fixture = new StrictObservationFixture(root.get("scenarios").get(0));
        var tools = new LiveEvalRunner().buildMockedToolsFactory(root.get("scenarios").get(0), java.util.List.of("nginx"), fixture).createAgentTools();
        assertThat(tools.get_system_status("banana")).startsWith("잘못된 resource");
        Instant start = Instant.now().minusSeconds(60);
        assertThat(fixture.query("sum(node_cpu_seconds_total) /", start, Instant.now())).startsWith("잘못된 PromQL");
        assertThat(fixture.query("node_cpu_nonexistent_metric", start, Instant.now())).startsWith("데이터 없음");
        assertThat(fixture.query("node_load5{instance=\"wrong-host\"}", start, Instant.now())).startsWith("데이터 없음");
        assertThat(fixture.query("node_cpu_seconds_total{instance=\"wrong-host\"}", start, Instant.now())).startsWith("EVAL_UNSUPPORTED_FIXTURE");
        assertThat(fixture.query("node_cpu_seconds_total", start, Instant.now())).contains("관측 요약", "92%");
        assertThat(fixture.query("100 - node_cpu_seconds_total", start, Instant.now())).startsWith("EVAL_UNSUPPORTED_FIXTURE");
        assertThat(fixture.hasUnsupportedQueries()).isTrue();
        assertThat(fixture.verify("WrongAlert", "{} ").path("status").asText()).isEqualTo("UNKNOWN");
        assertThat(fixture.query("node_cpu_seconds_total", start.minusSeconds(600), start)).startsWith("데이터 없음");
    }

    @Test
    void logsRequireExactSourceAndRespectBounds() throws Exception {
        var mapper = new ObjectMapper();
        var scene = mapper.readTree("""
                {"alert":{"name":"Test"},"mocks":{"loki":[{"keyword":"nginx","lines":["a","b"]}]}}
                """);
        var fixture = new StrictObservationFixture(scene, java.util.List.of("nginx", "nginx-other"));
        var start = Instant.now().minusSeconds(60);
        assertThat(fixture.logs("{job=\"docker\"} |= `nginx`", start, Instant.now(), 1)).containsExactly("a");
        assertThat(fixture.logs("{job=\"docker\"} |= `nginx-other`", start, Instant.now(), 10)).isEmpty();
        assertThat(fixture.logs("{job=\"journal\"} |= `nginx`", start, Instant.now(), 10)).isEmpty();
        assertThat(fixture.hasUnsupportedQueries()).isTrue();
    }
}
