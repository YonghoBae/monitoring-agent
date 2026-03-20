package io.ohgnoy.monitoring.agent.dto;

public record CommandResult(int exitCode, String output, String errorOutput) {

    public boolean isSuccess() {
        return exitCode == 0;
    }
}
