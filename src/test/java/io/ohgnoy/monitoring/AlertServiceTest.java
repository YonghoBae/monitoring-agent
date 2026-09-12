package io.ohgnoy.monitoring;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.alert.AlertEventRepository;
import io.ohgnoy.monitoring.application.alert.AlertService;
import io.ohgnoy.monitoring.application.pipeline.AlertIndexingEvent;
import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import io.ohgnoy.monitoring.application.pipeline.AlertCreatedEvent;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.context.ApplicationEventPublisher;

import java.lang.reflect.Field;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@DisplayName("AlertService 단위 테스트")
class AlertServiceTest {

    @Mock
    private AlertEventRepository alertEventRepository;

    @Mock
    private AlertVectorService alertVectorService;

    @Mock
    private ApplicationEventPublisher eventPublisher;

    @Mock
    private ObjectMapper objectMapper;

    @InjectMocks
    private AlertService alertService;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    @DisplayName("createAlert - ERROR 레벨이면 저장 + 벡터 인덱싱 + 파이프라인 이벤트를 발행한다")
    void createAlert_error_savesAndPublishesEvent() {
        // given
        when(alertEventRepository.save(any(AlertEvent.class)))
                .thenAnswer(invocation -> {
                    AlertEvent actual = invocation.getArgument(0);
                    setId(actual, 42L);
                    return actual;
                });

        // when
        AlertEvent result = alertService.createAlert("ERROR", "database down");

        // then
        assertThat(result.getId()).isEqualTo(42L);
        assertThat(result.getLevel()).isEqualTo("ERROR");
        assertThat(result.getMessage()).isEqualTo("database down");
        assertThat(result.isResolved()).isFalse();

        verify(alertEventRepository).save(any(AlertEvent.class));
        ArgumentCaptor<Object> eventCaptor = ArgumentCaptor.forClass(Object.class);
        verify(eventPublisher, times(2)).publishEvent(eventCaptor.capture());
        assertThat(eventCaptor.getAllValues())
                .anySatisfy(event -> {
                    assertThat(event).isInstanceOf(AlertIndexingEvent.class);
                    assertThat(((AlertIndexingEvent) event).alertId()).isEqualTo(42L);
                })
                .anySatisfy(event -> {
                    assertThat(event).isInstanceOf(AlertCreatedEvent.class);
                    assertThat(((AlertCreatedEvent) event).alertId()).isEqualTo(42L);
                });
    }

    @Test
    @DisplayName("createAlert - INFO 레벨이면 이벤트를 발행하지 않는다")
    void createAlert_info_doesNotPublishEvent() {
        // given
        when(alertEventRepository.save(any(AlertEvent.class)))
                .thenAnswer(invocation -> {
                    AlertEvent actual = invocation.getArgument(0);
                    setId(actual, 100L);
                    return actual;
                });

        // when
        alertService.createAlert("INFO", "just info");

        // then
        verify(alertEventRepository).save(any(AlertEvent.class));
        ArgumentCaptor<Object> eventCaptor = ArgumentCaptor.forClass(Object.class);
        verify(eventPublisher).publishEvent(eventCaptor.capture());
        assertThat(eventCaptor.getValue()).isInstanceOf(AlertIndexingEvent.class);
        assertThat(((AlertIndexingEvent) eventCaptor.getValue()).alertId()).isEqualTo(100L);
    }

    @Test
    @DisplayName("processWebhookPayload - 같은 startsAt의 미해결 알람이 있으면 새로 저장하지 않는다")
    void processWebhookPayload_duplicateFiring_skipsCreation() throws Exception {
        // given
        ObjectMapper realMapper = new ObjectMapper();
        realMapper.registerModule(new com.fasterxml.jackson.datatype.jsr310.JavaTimeModule());
        AlertService service = new AlertService(alertEventRepository, eventPublisher, realMapper);

        String json = """
                {"alerts":[{"status":"firing",
                  "labels":{"alertname":"HostSystemdServiceCrashed","severity":"warning"},
                  "annotations":{"summary":"service failed"},
                  "startsAt":"2026-08-13T05:49:01.032Z"}]}
                """;
        var payload = realMapper.readValue(json,
                io.ohgnoy.monitoring.web.dto.AlertmanagerWebhookPayload.class);
        String labelsJson = realMapper.writeValueAsString(
                new java.util.TreeMap<>(payload.getAlerts().get(0).getLabels()));

        AlertEvent existing = new AlertEvent("WARNING", "[HostSystemdServiceCrashed] service failed",
                "HostSystemdServiceCrashed", labelsJson, "service failed", "",
                java.time.Instant.parse("2026-08-13T05:49:01.032Z"), null);
        setId(existing, 7L);
        when(alertEventRepository.findByAlertNameAndLabelsJsonAndResolvedFalse(
                "HostSystemdServiceCrashed", labelsJson))
                .thenReturn(List.of(existing));

        // when
        service.processWebhookPayload(payload);

        // then
        verify(alertEventRepository, never()).save(any(AlertEvent.class));
        verify(eventPublisher, never()).publishEvent(any());
    }

    @Test
    @DisplayName("processWebhookPayload - startsAt이 다르면 새 발화로 저장한다")
    void processWebhookPayload_newFiring_createsEvent() throws Exception {
        // given
        ObjectMapper realMapper = new ObjectMapper();
        realMapper.registerModule(new com.fasterxml.jackson.datatype.jsr310.JavaTimeModule());
        AlertService service = new AlertService(alertEventRepository, eventPublisher, realMapper);

        String json = """
                {"alerts":[{"status":"firing",
                  "labels":{"alertname":"HostSystemdServiceCrashed","severity":"warning"},
                  "annotations":{"summary":"service failed"},
                  "startsAt":"2026-08-14T00:00:00Z"}]}
                """;
        var payload = realMapper.readValue(json,
                io.ohgnoy.monitoring.web.dto.AlertmanagerWebhookPayload.class);

        AlertEvent existing = new AlertEvent("WARNING", "old", "HostSystemdServiceCrashed",
                "{}", "old", "", java.time.Instant.parse("2026-08-13T05:49:01.032Z"), null);
        setId(existing, 7L);
        when(alertEventRepository.findByAlertNameAndLabelsJsonAndResolvedFalse(
                eq("HostSystemdServiceCrashed"), any()))
                .thenReturn(List.of(existing));
        when(alertEventRepository.save(any(AlertEvent.class)))
                .thenAnswer(invocation -> {
                    AlertEvent actual = invocation.getArgument(0);
                    setId(actual, 8L);
                    return actual;
                });

        // when
        service.processWebhookPayload(payload);

        // then
        verify(alertEventRepository).save(any(AlertEvent.class));
    }

    @Test
    @DisplayName("getRecentOpenAlerts - 레포지토리에서 최근 미해결 알람만 조회한다")
    void getRecentOpenAlerts_delegatesToRepository() {
        // given
        List<AlertEvent> events = List.of(new AlertEvent("WARN", "disk almost full"));
        when(alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc())
                .thenReturn(events);

        // when
        List<AlertEvent> result = alertService.getRecentOpenAlerts();

        // then
        assertThat(result).isSameAs(events);
        verify(alertEventRepository).findTop20ByResolvedFalseOrderByCreatedAtDesc();
        verifyNoInteractions(alertVectorService, eventPublisher);
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
