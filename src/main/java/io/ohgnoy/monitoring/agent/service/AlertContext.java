package io.ohgnoy.monitoring.agent.service;

import java.util.List;

public record AlertContext(
        List<String> metricSummaries,
        List<String> logLines,
        List<String> concurrentAlertNames
) {
    public boolean isEmpty() {
        return metricSummaries.isEmpty() && logLines.isEmpty() && concurrentAlertNames.isEmpty();
    }
}
