package io.ohgnoy.monitoring.agent.dto;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;

import java.time.LocalDateTime;

public class AlertResponse {
    private Long id;
    private String level;
    private String message;
    private LocalDateTime createdAt;
    private boolean resolved;

    public AlertResponse(AlertEvent alert) {
        this.id = alert.getId();
        this.level = alert.getLevel();
        this.message = alert.getMessage();
        this.createdAt = alert.getCreatedAt();
        this.resolved = alert.isResolved();
    }

    public Long getId() {
        return id;
    }

    public String getLevel() {
        return level;
    }

    public String getMessage() {
        return message;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public boolean isResolved() {
        return resolved;
    }
}
