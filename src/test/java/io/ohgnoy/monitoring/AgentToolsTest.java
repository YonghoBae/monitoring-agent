package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.application.agent.tools.AgentTools;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.loki.LokiQueryService;
import io.ohgnoy.monitoring.infrastructure.prometheus.AlertVerifier;
import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AgentToolsTest {

    @Test
    void listMiscDelegatesToMetricListLookup() {
        PrometheusQueryService prometheusQuery = mock(PrometheusQueryService.class);
        when(prometheusQuery.listMetrics("memory"))
                .thenReturn(List.of("node_memory_MemAvailable_bytes", "node_memory_MemTotal_bytes"));

        AgentTools tools = new AgentTools(
                mock(AlertVerifier.class),
                prometheusQuery,
                mock(LokiQueryService.class),
                mock(AlertVectorService.class),
                mock(CommandExecutorService.class)
        );

        String result = tools.list_misc("memory");

        assertThat(result)
                .contains("node_memory_MemAvailable_bytes")
                .contains("node_memory_MemTotal_bytes");
        assertThat(tools.getCallCount()).isEqualTo(1);
        assertThat(tools.getReasoningLog()).contains("list_misc");
    }
}
