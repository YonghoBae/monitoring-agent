package io.ohgnoy.monitoring.agent;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.web.client.RestClient;

import java.time.LocalDateTime;
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

    private DiscordNotificationService discordNotificationService;

    private static final String WEBHOOK_URL = "https://discord.com/api/webhooks/test";

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);

        when(restClientBuilder.build()).thenReturn(restClient);
        when(restClient.post()).thenReturn(requestBodyUriSpec);
        when(requestBodyUriSpec.uri(any(String.class))).thenReturn(requestBodySpec);

        // 🔑 여기! 타입을 명시적으로 Map.class로
        when(requestBodySpec.body(any(Map.class))).thenReturn(requestBodySpec);

        when(requestBodySpec.retrieve()).thenReturn(responseSpec);
        when(responseSpec.toBodilessEntity()).thenReturn(null);

        discordNotificationService = new DiscordNotificationService(restClientBuilder, WEBHOOK_URL);
    }


    @Test
    @DisplayName("sendAlert - Alert 정보를 content 문자열로 만들어 Webhook으로 전송한다")
    void sendAlert_buildsContentAndPostsToWebhook() {
        // given
        AlertEvent alert = new AlertEvent("ERROR", "database down");
        setIdAndCreatedAt(alert, 99L, LocalDateTime.of(2025, 11, 23, 19, 30));

        // when
        discordNotificationService.sendAlert(alert);

        // then
        // 1) post → uri(webhookUrl) 호출 여부
        verify(restClient).post();
        verify(requestBodyUriSpec).uri(WEBHOOK_URL);

        // 2) body에 어떤 payload가 들어갔는지 캡쳐
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

        // content에 우리가 기대하는 값들이 포함되어 있는지만 확인 (완전 일치까지는 굳이 필요 없음)
        assertThat(content)
                .contains("Monitoring Alert")
                .contains("ERROR")
                .contains("database down")
                .contains("99"); // ID
    }

    private static void setIdAndCreatedAt(AlertEvent alert, Long id, LocalDateTime createdAt) {
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
