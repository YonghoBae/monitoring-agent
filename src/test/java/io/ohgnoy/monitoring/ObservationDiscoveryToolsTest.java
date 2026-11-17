package io.ohgnoy.monitoring;
import io.ohgnoy.monitoring.application.agent.tools.ObservationDiscoveryTools;
import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.loki.LokiQueryService;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.mockito.Mockito.*;
import static org.assertj.core.api.Assertions.*;

class ObservationDiscoveryToolsTest {
    @Test void logsAreScopedByFilenameWithoutRequiringNameInBody(){
        var command=mock(CommandExecutorService.class);var logs=mock(LokiQueryService.class);
        when(command.containerLogPath("stopped-app")).thenReturn("/var/lib/docker/containers/abc/abc-json.log");
        when(logs.queryRecentLogs(eq("{job=\"docker\",filename=\"/var/lib/docker/containers/abc/abc-json.log\"}"),any(),any(),eq(30)))
                .thenReturn(List.of("Error: MYSQL_HOST is not defined"));
        var tools=new ObservationDiscoveryTools(mock(PrometheusQueryService.class),command,logs);
        assertThat(tools.read_container_logs("stopped-app",30)).contains("MYSQL_HOST");
        assertThatThrownBy(()->tools.read_container_logs("stopped-app",0)).isInstanceOf(IllegalArgumentException.class);
        verify(command,never()).listContainers();verify(command,never()).execute(anyString());
    }
    @Test void containerInspectionDelegatesOnlyToReadOnlyService(){
        var command=mock(CommandExecutorService.class);
        when(command.inspectContainer("web")).thenReturn("{\"status\":\"running\",\"health\":\"healthy\"}");
        var tools=new ObservationDiscoveryTools(mock(PrometheusQueryService.class),command);
        assertThat(tools.inspect_container("web")).contains("healthy");
        verify(command,never()).execute(anyString());
        when(command.inspectContainer("missing")).thenThrow(new IllegalStateException("unavailable"));
        assertThatThrownBy(()->tools.inspect_container("missing")).isInstanceOf(IllegalStateException.class);
    }
    @Test void preservesActualLabelsAndRejectsExpressions(){
        var service=mock(PrometheusQueryService.class);
        when(service.querySummary(eq("pg_stat_activity_count"),eq("pg_stat_activity_count"),any(),any())).thenReturn("datname=db,state=idle:82");
        var tools=new ObservationDiscoveryTools(service);
        assertThat(tools.describe_metric("pg_stat_activity_count")).contains("datname=db");
        assertThatThrownBy(()->tools.describe_metric("pg_stat_activity_count{database=\"wrong\"}")).isInstanceOf(IllegalArgumentException.class);
        assertThat(tools.describe_metric("missing_metric")).contains("구분 불가");
    }
}
