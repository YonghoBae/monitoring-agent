package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.application.agent.tools.AgentTools;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.loki.LokiQueryService;
import io.ohgnoy.monitoring.infrastructure.prometheus.AlertVerifier;
import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class ContainerObservationContractTest {
    @Test
    void stoppedContainersStillHaveQueryableHistoricalLogs() {
        var executor = mock(CommandExecutorService.class);
        when(executor.listContainers()).thenReturn(List.of("other-container"));
        var loki = mock(LokiQueryService.class);
        when(loki.queryRecentLogs(anyString(), any(), any(), anyInt())).thenReturn(List.of("nginx exited with bind error"));
        var tools = new AgentTools(mock(AlertVerifier.class), mock(PrometheusQueryService.class), loki,
                mock(AlertVectorService.class), executor);
        assertThat(tools.query_loki("nginx", "30")).contains("bind error");
        verify(loki).queryRecentLogs(contains("nginx"), any(), any(), anyInt());
    }

    @Test
    void dockerInventoryTimeoutIsNotReportedAsZeroContainers() throws Exception {
        Process process = mock(Process.class);
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream(new byte[0]));
        when(process.waitFor(5, TimeUnit.SECONDS)).thenReturn(false);
        try (var builders = mockConstruction(ProcessBuilder.class, (builder, context) -> {
            when(builder.redirectErrorStream(true)).thenReturn(builder);
            when(builder.start()).thenReturn(process);
        })) {
            assertThatThrownBy(() -> new CommandExecutorService().listContainers()).isInstanceOf(IllegalStateException.class);
            verify(process).destroyForcibly();
        }
    }

    @Test
    void dockerInventoryFailureIsNotReportedAsZeroContainers() throws Exception {
        Process process = mock(Process.class);
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream(new byte[0]));
        when(process.waitFor(5, TimeUnit.SECONDS)).thenReturn(true);
        when(process.exitValue()).thenReturn(1);
        try (var builders = mockConstruction(ProcessBuilder.class, (builder, context) -> {
            when(builder.redirectErrorStream(true)).thenReturn(builder);
            when(builder.start()).thenReturn(process);
        })) {
            assertThatThrownBy(() -> new CommandExecutorService().listContainers()).isInstanceOf(IllegalStateException.class);
        }
    }
}
