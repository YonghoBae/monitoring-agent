package io.ohgnoy.monitoring.agent;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

import java.lang.reflect.Field;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class AlertServiceTest {

    @Mock
    private AlertEventRepository alertEventRepository;

    @Mock
    private AlertVectorService alertVectorService;

    @InjectMocks
    private AlertService alertService;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    void createAlert_persistsAndIndexes() {
        when(alertEventRepository.save(any(AlertEvent.class)))
                .thenAnswer(invocation -> {
                    AlertEvent actual = invocation.getArgument(0);
                    setId(actual, 42L);
                    return actual;
                });

        AlertEvent result = alertService.createAlert("ERROR", "database down");

        assertThat(result.getId()).isEqualTo(42L);
        assertThat(result.getLevel()).isEqualTo("ERROR");
        assertThat(result.getMessage()).isEqualTo("database down");
        assertThat(result.isResolved()).isFalse();
        verify(alertEventRepository).save(any(AlertEvent.class));
        verify(alertVectorService).indexAlert(result);
    }

    @Test
    void getRecentOpenAlerts_delegatesToRepository() {
        List<AlertEvent> events = List.of(new AlertEvent("WARN", "disk almost full"));
        when(alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc()).thenReturn(events);

        List<AlertEvent> result = alertService.getRecentOpenAlerts();

        assertThat(result).isSameAs(events);
        verify(alertEventRepository).findTop20ByResolvedFalseOrderByCreatedAtDesc();
        verifyNoInteractions(alertVectorService);
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
