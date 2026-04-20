package io.ohgnoy.monitoring.infrastructure.command;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.LoggerFactory;

import java.util.Map;

public class TemplateResolver {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @SuppressWarnings("unchecked")
    public static String resolve(String template, String labelsJson) {
        if (template == null || labelsJson == null || labelsJson.isBlank()) {
            return template;
        }
        try {
            Map<String, String> labels = MAPPER.readValue(labelsJson, Map.class);
            for (Map.Entry<String, String> e : labels.entrySet()) {
                template = template.replace("{" + e.getKey() + "}", e.getValue());
            }
        } catch (Exception e) {
            LoggerFactory.getLogger(TemplateResolver.class)
                    .warn("라벨 JSON 파싱 실패 — template='{}', labelsJson='{}': {}",
                            template, labelsJson, e.getMessage());
        }
        return template;
    }
}
