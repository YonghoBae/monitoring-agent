package io.ohgnoy.monitoring.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.service.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.web.client.RestClient;

import java.time.Instant;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@DisplayName("DiscordNotificationService 단위 테스트")
class DiscordNotificationServiceTest {

    @Mock
    private RestClient.Builder restClientBuilder;

    @Mock
    private RestClient restClient;

    @Mock
    private RestClient.RequestBodyUriSpec requestBodyUriSpec;

    @Mock
    private RestClient.RequestBodySpec requestBodySpec;

    @Mock
    private RestClient.ResponseSpec responseSpec;

    @Mock
    private PendingApprovalStore pendingApprovalStore;

    @Mock
    private ConversationSessionStore conversationSessionStore;

    private DiscordNotificationService discordNotificationService;

    private static final String WEBHOOK_URL = "https://discord.com/api/webhooks/test";

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);

        when(restClientBuilder.build()).thenReturn(restClient);
        when(restClient.post()).thenReturn(requestBodyUriSpec);
        when(requestBodyUriSpec.uri(any(String.class))).thenReturn(requestBodySpec);
        when(requestBodySpec.body(any(Map.class))).thenReturn(requestBodySpec);
        when(requestBodySpec.retrieve()).thenReturn(responseSpec);
        when(responseSpec.toBodilessEntity()).thenReturn(null);

        discordNotificationService = new DiscordNotificationService(
                restClientBuilder, WEBHOOK_URL, "", new ObjectMapper(),
                pendingApprovalStore, conversationSessionStore);
    }

    @Test
    @DisplayName("sendAlert - Alert 정보를 content 문자열로 만들어 Webhook으로 전송한다")
    void sendAlert_buildsContentAndPostsToWebhook() {
        // given
        AlertEvent alert = new AlertEvent("ERROR", "database down");
        setIdAndCreatedAt(alert, 99L, Instant.parse("2025-11-23T19:30:00Z"));

        ActionRecommendation recommendation =
                new ActionRecommendation("수동 조사", ActionRecommendation.Category.NONE, null);

        // when
        discordNotificationService.sendAlert(alert, "agent analysis text", null, recommendation);

        // then
        verify(restClient).post();
        verify(requestBodyUriSpec).uri(WEBHOOK_URL);

        ArgumentCaptor<Object> bodyCaptor = ArgumentCaptor.forClass(Object.class);
        verify(requestBodySpec).body(bodyCaptor.capture());
        verify(requestBodySpec).retrieve();
        verify(responseSpec).toBodilessEntity();

        Object body = bodyCaptor.getValue();
        assertThat(body).isInstanceOf(Map.class);

        @SuppressWarnings("unchecked")
        Map<String, Object> payload = (Map<String, Object>) body;
        assertThat(payload).containsKey("content");
        String content = (String) payload.get("content");

        assertThat(content)
                .contains("Monitoring Alert")
                .contains("ERROR")
                .contains("database down")
                .contains("99");
    }

    @Test
    @DisplayName("sendAlert - NEEDS_APPROVAL이고 command가 있으면 PendingApprovalStore에 저장한다")
    void sendAlert_needsApproval_storesPendingApproval() {
        // given
        AlertEvent alert = new AlertEvent("CRITICAL", "[ContainerRestarting] test");
        setIdAndCreatedAt(alert, 10L, Instant.now());

        ActionRecommendation recommendation = new ActionRecommendation(
                "컨테이너 재시작", ActionRecommendation.Category.NEEDS_APPROVAL, "docker restart my-app");

        // when
        discordNotificationService.sendAlert(alert, "분석 결과", null, recommendation);

        // then
        verify(pendingApprovalStore).store("docker restart my-app", 10L, "");
    }

    @Test
    @DisplayName("sendAlert - NONE 카테고리면 PendingApprovalStore에 저장하지 않는다")
    void sendAlert_noneCategory_doesNotStorePending() {
        // given
        AlertEvent alert = new AlertEvent("ERROR", "cpu high");
        setIdAndCreatedAt(alert, 20L, Instant.now());

        ActionRecommendation recommendation =
                new ActionRecommendation("수동 조사", ActionRecommendation.Category.NONE, null);

        // when
        discordNotificationService.sendAlert(alert, "분석 결과", null, recommendation);

        // then
        verifyNoInteractions(pendingApprovalStore);
    }

    private static void setIdAndCreatedAt(AlertEvent alert, Long id, Instant createdAt) {
        try {
            var idField = AlertEvent.class.getDeclaredField("id");
            idField.setAccessible(true);
            idField.set(alert, id);

            var createdAtField = AlertEvent.class.getDeclaredField("createdAt");
            createdAtField.setAccessible(true);
            createdAtField.set(alert, createdAt);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("필드 설정 실패", e);
        }
    }
}
