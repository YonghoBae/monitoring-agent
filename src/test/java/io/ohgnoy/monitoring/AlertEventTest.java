package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AlertEventTest {

    @Test
    void constructor_setsDefaultFields() {
        AlertEvent alert = new AlertEvent("WARN", "cpu usage high");

        assertThat(alert.getLevel()).isEqualTo("WARN");
        assertThat(alert.getMessage()).isEqualTo("cpu usage high");
        assertThat(alert.isResolved()).isFalse();
    }

    @Test
    void resolve_changesResolvedFlag() {
        AlertEvent alert = new AlertEvent("INFO", "done");

        alert.resolve();

        assertThat(alert.isResolved()).isTrue();
    }

    @Test
    void getAgentIterations_returnsZeroWhenUnanalyzed() {
        // 분석 전 행은 agent_iterations가 NULL — 재시작 후 재로드 시 NPE 없이 0으로 읽혀야 한다
        AlertEvent alert = new AlertEvent("WARN", "pending alert");

        assertThat(alert.getAgentIterations()).isZero();
    }
}
