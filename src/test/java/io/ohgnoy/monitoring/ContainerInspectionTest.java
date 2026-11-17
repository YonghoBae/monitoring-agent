package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import com.fasterxml.jackson.databind.ObjectMapper;
import static org.assertj.core.api.Assertions.*;

class ContainerInspectionTest {
    @Test
    @EnabledIfEnvironmentVariable(named="RUN_DOCKER_INSPECT_TEST", matches="1")
    void actualReadOnlyDockerOutputContainsOnlyTheAllowedFields() throws Exception {
        String result = new CommandExecutorService().inspectContainer("monitoring-agent-app");
        var data = new ObjectMapper().readTree(result);
        var fields = new java.util.HashSet<String>(); data.fieldNames().forEachRemaining(fields::add);
        assertThat(fields).containsExactlyInAnyOrder("name", "image", "status", "oomKilled", "exitCode", "restartCount", "health", "ports");
        assertThat(data.path("image").asText()).isNotBlank();
        assertThat(data.path("name").asText()).isEqualTo("/monitoring-agent-app");
        assertThat(new CommandExecutorService().containerLogPath("monitoring-agent-app")).startsWith("/").endsWith(".log");
    }
    @Test void rejectsOptionsShellSyntaxAndMultipleTargetsBeforeStartingDocker() {
        var service = new CommandExecutorService();
        for (String name : new String[]{"--all", "web db", "web;id", "$(id)", "../web", ""}) {
            assertThatThrownBy(() -> service.inspectContainer(name)).isInstanceOf(IllegalArgumentException.class);
        }
        assertThatThrownBy(() -> service.inspectContainer(null)).isInstanceOf(IllegalArgumentException.class);
    }
}
