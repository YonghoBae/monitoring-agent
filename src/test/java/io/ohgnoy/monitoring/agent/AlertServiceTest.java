package io.ohgnoy.monitoring.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.repository.AlertEventRepository;
import io.ohgnoy.monitoring.agent.service.AlertService;
import io.ohgnoy.monitoring.agent.service.AlertVectorService;
import io.ohgnoy.monitoring.agent.service.pipeline.AlertCreatedEvent;
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
        verify(alertVectorService).indexAlert(result);

        ArgumentCaptor<AlertCreatedEvent> eventCaptor = ArgumentCaptor.forClass(AlertCreatedEvent.class);
        verify(eventPublisher).publishEvent(eventCaptor.capture());
        assertThat(eventCaptor.getValue().alertId()).isEqualTo(42L);
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
        verify(alertVectorService).indexAlert(any());
        verify(eventPublisher, never()).publishEvent(any());
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
