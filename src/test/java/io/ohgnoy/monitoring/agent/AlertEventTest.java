package io.ohgnoy.monitoring.agent;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AlertEventTest {

    @Test
    void constructor_setsDefaultFields() {
        AlertEvent alert = new AlertEvent("WARN", "cpu usage high");

        assertThat(alert.getLevel()).isEqualTo("WARN");
        assertThat(alert.getMessage()).isEqualTo("cpu usage high");
        assertThat(alert.getCreatedAt()).isNotNull();
        assertThat(alert.isResolved()).isFalse();
    }

    @Test
    void resolve_changesResolvedFlag() {
        AlertEvent alert = new AlertEvent("INFO", "done");

        alert.resolve();

        assertThat(alert.isResolved()).isTrue();
    }
}
