package io.ohgnoy.monitoring.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;

import org.springframework.ai.document.Document;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(AlertController.class)
@AutoConfigureMockMvc(addFilters = false)
class AlertControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private AlertService alertService;

    @MockBean
    private AlertVectorService alertVectorService;

    @Test
    void createAlert_returnsCreatedPayload() throws Exception {
        AlertEvent saved = new AlertEvent("WARN", "database is slow");
        setId(saved, 7L);

        when(alertService.createAlert(eq("WARN"), eq("database is slow"))).thenReturn(saved);

        String payload = objectMapper.writeValueAsString(Map.of(
                "level", "WARN",
                "message", "database is slow"
        ));

        mockMvc.perform(post("/api/alerts")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(7))
                .andExpect(jsonPath("$.level").value("WARN"))
                .andExpect(jsonPath("$.message").value("database is slow"))
                .andExpect(jsonPath("$.resolved").value(false));

        verify(alertService).createAlert(eq("WARN"), eq("database is slow"));
    }

    @Test
    void getOpenAlerts_returnsRecentRecords() throws Exception {
        AlertEvent event = new AlertEvent("INFO", "processing done");
        setId(event, 3L);
        when(alertService.getRecentOpenAlerts()).thenReturn(List.of(event));

        mockMvc.perform(get("/api/alerts/open"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").value(3))
                .andExpect(jsonPath("$[0].level").value("INFO"))
                .andExpect(jsonPath("$[0].message").value("processing done"));
    }

    @Test
    void searchSimilar_returnsVectorDocuments() throws Exception {
        Document doc = new Document("doc-1", "timeout reached", Map.of("level", "ERROR"));
        when(alertVectorService.searchSimilar("timeout", 3)).thenReturn(List.of(doc));

        mockMvc.perform(get("/api/alerts/similar")
                        .param("query", "timeout")
                        .param("topK", "3"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").value("doc-1"))
                .andExpect(jsonPath("$[0].text").value("timeout reached"))
                .andExpect(jsonPath("$[0].metadata.level").value("ERROR"));

        verify(alertVectorService).searchSimilar("timeout", 3);
    }

    private static void setId(AlertEvent alertEvent, Long id) {
        try {
            Field idField = AlertEvent.class.getDeclaredField("id");
            idField.setAccessible(true);
            idField.set(alertEvent, id);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("id 필드를 설정할 수 없습니다.", e);
        }
    }
}
