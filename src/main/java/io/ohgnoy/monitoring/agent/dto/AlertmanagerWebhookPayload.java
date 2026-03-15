package io.ohgnoy.monitoring.agent.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;
import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
public class AlertmanagerWebhookPayload {

    private String status;
    private Map<String, String> groupLabels;
    private Map<String, String> commonLabels;
    private Map<String, String> commonAnnotations;
    private String externalURL;
    private List<AlertmanagerAlert> alerts;

    public AlertmanagerWebhookPayload() {
    }

    public String getStatus() {
        return status;
    }

    public Map<String, String> getGroupLabels() {
        return groupLabels;
    }

    public Map<String, String> getCommonLabels() {
        return commonLabels;
    }

    public Map<String, String> getCommonAnnotations() {
        return commonAnnotations;
    }

    public String getExternalURL() {
        return externalURL;
    }

    public List<AlertmanagerAlert> getAlerts() {
        return alerts;
    }
}
