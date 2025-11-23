package io.ohgnoy.monitoring.agent;

public class CreateAlertRequest {
    private String level;
    private String message;

    public String getLevel() {
        return level;
    }

    public String getMessage() {
        return message;
    }
}
