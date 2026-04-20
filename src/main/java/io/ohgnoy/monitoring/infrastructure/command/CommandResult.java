package io.ohgnoy.monitoring.infrastructure.command;

public record CommandResult(int exitCode, String output, String errorOutput) {

    public boolean isSuccess() {
        return exitCode == 0;
    }
}
