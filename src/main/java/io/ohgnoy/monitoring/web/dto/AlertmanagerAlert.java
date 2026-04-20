package io.ohgnoy.monitoring.web.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.time.Instant;
import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
public class AlertmanagerAlert {

    private String status;
    private Map<String, String> labels;
    private Map<String, String> annotations;
    private Instant startsAt;
    private Instant endsAt;
    private String generatorURL;

    public AlertmanagerAlert() {
    }

    public String getStatus() {
        return status;
    }

    public Map<String, String> getLabels() {
        return labels;
    }

    public Map<String, String> getAnnotations() {
        return annotations;
    }

    public Instant getStartsAt() {
        return startsAt;
    }

    public Instant getEndsAt() {
        return endsAt;
    }

    public String getGeneratorURL() {
        return generatorURL;
    }
}
