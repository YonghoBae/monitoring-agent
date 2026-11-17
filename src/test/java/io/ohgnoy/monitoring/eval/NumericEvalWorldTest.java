package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "RUN_NUMERIC_FIXTURE_TESTS", matches = "1")
class NumericEvalWorldTest {
    @Test
    void productionToolsUseActualArithmeticAndLogicalClock() throws Exception {
        var scene = new ObjectMapper().readTree("""
                {"id":"bridge-test","alert":{"name":"Cpu","labels":{"instance":"node-1"}},
                 "world":{"evaluation_time":"2026-08-15T12:00:00Z","step_seconds":60,
                  "series":[{"metric":"node_cpu_seconds_total","labels":{"instance":"node-1","cpu":"0","mode":"idle"},"samples":[[-7200,0],[0,2520]]}],
                  "verify":{"status":"CONFIRMED","value":"65"},"containers":["nginx"],
                  "logs":[{"source":"docker","name":"nginx","entries":[{"offset_seconds":-30,"line":"nginx started"}]}],"rag":[]}}
                """);
        try (var world = new NumericEvalWorld(scene)) {
            var tools = world.toolsFactory().createAgentTools();
            assertThat(tools.list_metrics("cpu")).contains("node_cpu_seconds_total");
            assertThat(world.trace().path("observations").findValuesAsText("target"))
                    .anySatisfy(target -> assertThat(target)
                            .startsWith("/api/v1/label/__name__/values?match[]=")
                            .contains("cpu"));
            assertThat(tools.get_system_status("cpu")).contains("65.00 %", "node-1");
            assertThat(tools.query_prometheus("100 * (1 - avg(rate(node_cpu_seconds_total{mode=\"idle\"}[5m])))", "30")).contains("65.00");
            assertThat(tools.query_prometheus("node_cpu_seconds_total{instance=\"wrong\"}", "30")).contains("데이터 없음");
            assertThatThrownBy(() -> tools.query_prometheus("sum(node_cpu_seconds_total) /", "30")).isInstanceOf(IllegalStateException.class);
            assertThat(tools.verify_alert("Wrong", "{}")).startsWith("UNKNOWN");
            assertThat(tools.query_loki("nginx", "30")).contains("nginx started");
            assertThat(world.trace().path("observations").size()).isGreaterThan(4);
            assertThat(world.trace().path("events")).isEmpty();
        }
    }
}
