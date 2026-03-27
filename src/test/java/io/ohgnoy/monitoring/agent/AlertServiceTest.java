package io.ohgnoy.monitoring.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.dto.CommandResult;
import io.ohgnoy.monitoring.agent.repository.AlertEventRepository;
import io.ohgnoy.monitoring.agent.service.*;
import io.ohgnoy.monitoring.agent.service.agent.AgentResult;
import io.ohgnoy.monitoring.agent.service.agent.OrchestratorAgent;
import io.ohgnoy.monitoring.agent.service.agent.ReActAgent;
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

    @Mock
    private ReActAgent reActAgent;

    @Mock
    private OrchestratorAgent orchestratorAgent;

    @Mock
    private AlertVerifier alertVerifier;

    @Mock
    private AlertPlaybook alertPlaybook;

    @Mock
    private CommandExecutorService commandExecutorService;

    @Mock
    private ObjectMapper objectMapper;

    @InjectMocks
    private AlertService alertService;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    @DisplayName("createAlert - ERROR 레벨이면 저장 + 벡터 인덱싱 + 에이전트 파이프라인 수행한다")
    void createAlert_error_runsAgentPipelineAndNotifiesDiscord() {
        // given
        when(alertEventRepository.save(any(AlertEvent.class)))
                .thenAnswer(invocation -> {
                    AlertEvent actual = invocation.getArgument(0);
                    setId(actual, 42L);
                    return actual;
                });
        // 동시 알람 없음 → ReActAgent 사용 (OrchestratorAgent 발동 조건 미충족)
        when(alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc())
                .thenReturn(List.of());

        ActionRecommendation recommendation = new ActionRecommendation(
                "컨테이너 재시작", ActionRecommendation.Category.NEEDS_APPROVAL, "docker restart test");
        AgentResult agentResult = new AgentResult("analysis", "tool-log", 2, "SUFFICIENT", recommendation);

        when(alertVerifier.verify(any(AlertEvent.class))).thenReturn(VerificationResult.unknown());
        when(alertPlaybook.lookup(any())).thenReturn(recommendation);
        when(reActAgent.run(any(AlertEvent.class), any())).thenReturn(agentResult);

        // when
        AlertEvent result = alertService.createAlert("ERROR", "database down");

        // then
        assertThat(result.getId()).isEqualTo(42L);
        assertThat(result.getLevel()).isEqualTo("ERROR");
        assertThat(result.getMessage()).isEqualTo("database down");
        assertThat(result.isResolved()).isFalse();

        verify(alertEventRepository).save(any(AlertEvent.class));
        verify(alertVectorService).indexAlert(result);
        verify(alertVerifier).verify(result);
        verify(alertPlaybook).lookup(any());
        verify(reActAgent).run(eq(result), any());
        verify(discordNotificationService).sendAlert(eq(result), eq("analysis"), any(), any());
        verify(commandExecutorService, never()).execute(any());
    }

    @Test
    @DisplayName("createAlert - AUTO 카테고리면 명령어를 즉시 실행하고 sendAutoExecuted를 호출한다")
    void createAlert_autoCategory_executesCommandImmediately() {
        // given
        when(alertEventRepository.save(any(AlertEvent.class)))
                .thenAnswer(invocation -> {
                    AlertEvent actual = invocation.getArgument(0);
                    setId(actual, 99L);
                    return actual;
                });
        when(alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc())
                .thenReturn(List.of());

        ActionRecommendation recommendation = new ActionRecommendation(
                "컨테이너 재시작", ActionRecommendation.Category.AUTO, "docker restart test-container");
        AgentResult agentResult = new AgentResult("analysis", "tool-log", 1, "SUFFICIENT", recommendation);

        when(alertVerifier.verify(any())).thenReturn(VerificationResult.confirmed("1", "now"));
        when(alertPlaybook.lookup(any())).thenReturn(recommendation);
        when(reActAgent.run(any(AlertEvent.class), any())).thenReturn(agentResult);
        when(commandExecutorService.execute(any()))
                .thenReturn(new CommandResult(0, "test-container\n", ""));

        // when
        AlertEvent result = alertService.createAlert("CRITICAL", "container restarting");

        // then
        verify(commandExecutorService).execute("docker restart test-container");
        verify(discordNotificationService).sendAutoExecuted(
                eq(result), eq("analysis"), any(), any(), eq("docker restart test-container"), any());
        verify(discordNotificationService, never()).sendAlert(any(), any(), any(), any());
    }

    @Test
    @DisplayName("createAlert - INFO 레벨이면 에이전트 파이프라인과 디스코드 전송을 하지 않는다")
    void createAlert_info_doesNotRunPipeline() {
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
        verifyNoInteractions(alertVerifier, alertPlaybook, reActAgent, orchestratorAgent,
                commandExecutorService, discordNotificationService);
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
        verifyNoInteractions(alertVectorService, discordNotificationService,
                reActAgent, orchestratorAgent);
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
