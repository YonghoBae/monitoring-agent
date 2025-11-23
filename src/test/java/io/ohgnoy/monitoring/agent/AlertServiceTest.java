package io.ohgnoy.monitoring.agent;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

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
    private DiscordNotificationService discordNotificationService;

    @InjectMocks
    private AlertService alertService;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    @DisplayName("createAlert - ERROR 레벨이면 저장 + 벡터 인덱싱 + 디스코드 전송까지 수행한다")
    void createAlert_error_persistsIndexesAndNotifiesDiscord() {
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
        verify(discordNotificationService).sendAlert(result);
        verifyNoMoreInteractions(alertEventRepository, alertVectorService, discordNotificationService);
    }

    @Test
    @DisplayName("createAlert - INFO 레벨이면 디스코드 전송은 하지 않는다")
    void createAlert_info_doesNotNotifyDiscord() {
        // given
        when(alertEventRepository.save(any(AlertEvent.class)))
                .thenAnswer(invocation -> {
                    AlertEvent actual = invocation.getArgument(0);
                    setId(actual, 100L);
                    return actual;
                });

        // when
        AlertEvent result = alertService.createAlert("INFO", "just info");

        // then
        verify(alertEventRepository).save(any(AlertEvent.class));
        verify(alertVectorService).indexAlert(result);
        verify(discordNotificationService, never()).sendAlert(any());
        verifyNoMoreInteractions(alertEventRepository, alertVectorService, discordNotificationService);
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
        verifyNoInteractions(alertVectorService, discordNotificationService);
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
