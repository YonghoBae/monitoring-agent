package io.ohgnoy.monitoring.agent.service.pipeline;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.dto.CommandResult;
import io.ohgnoy.monitoring.agent.repository.AlertEventRepository;
import io.ohgnoy.monitoring.agent.service.ActionRecommendation;
import io.ohgnoy.monitoring.agent.service.AlertPlaybook;
import io.ohgnoy.monitoring.agent.service.AlertVerifier;
import io.ohgnoy.monitoring.agent.service.CommandExecutorService;
import io.ohgnoy.monitoring.agent.service.DiscordNotificationService;
import io.ohgnoy.monitoring.agent.service.VerificationResult;
import io.ohgnoy.monitoring.agent.service.agent.AgentResult;
import io.ohgnoy.monitoring.agent.service.agent.OrchestratorAgent;
import io.ohgnoy.monitoring.agent.service.agent.ReActAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;

/**
 * 알람 분석 파이프라인을 4단계 Chain Workflow로 명시적으로 관리한다.
 *
 * Step 1: Verify     — Prometheus에서 알람이 현재도 유효한지 확인. STALE이면 early exit.
 * Step 2: Playbook   — alertName 기반으로 safety ceiling(허용 조치) 조회.
 * Step 3: Analyze    — ReAct 또는 Orchestrator로 AI 분석 실행. 결과를 DB에 저장.
 * Step 4: Authorize  — AUTO는 즉시 실행, 나머지는 Discord로 전송.
 *
 * 트랜잭션 전략: 이 클래스에 @Transactional 없음.
 * Spring Data의 save()/findById()가 각자 자체 트랜잭션을 보유하므로
 * LLM/외부 API 호출 중 DB 커넥션을 점유하지 않는다.
 */
@Component
public class AlertAnalysisChain {

    private static final Logger log = LoggerFactory.getLogger(AlertAnalysisChain.class);
    private static final int ORCHESTRATOR_THRESHOLD = 3;

    private final AlertEventRepository alertEventRepository;
    private final AlertVerifier alertVerifier;
    private final AlertPlaybook alertPlaybook;
    private final ReActAgent reActAgent;
    private final OrchestratorAgent orchestratorAgent;
    private final DiscordNotificationService discordNotificationService;
    private final CommandExecutorService commandExecutorService;
    private final ObjectMapper objectMapper;

    public AlertAnalysisChain(AlertEventRepository alertEventRepository,
                               AlertVerifier alertVerifier,
                               AlertPlaybook alertPlaybook,
                               ReActAgent reActAgent,
                               OrchestratorAgent orchestratorAgent,
                               DiscordNotificationService discordNotificationService,
                               CommandExecutorService commandExecutorService,
                               ObjectMapper objectMapper) {
        this.alertEventRepository = alertEventRepository;
        this.alertVerifier = alertVerifier;
        this.alertPlaybook = alertPlaybook;
        this.reActAgent = reActAgent;
        this.orchestratorAgent = orchestratorAgent;
        this.discordNotificationService = discordNotificationService;
        this.commandExecutorService = commandExecutorService;
        this.objectMapper = objectMapper;
    }

    public void run(Long alertId) {
        AlertEvent alert = alertEventRepository.findById(alertId)
                .orElseThrow(() -> new IllegalArgumentException("AlertEvent not found: " + alertId));

        log.info("[Chain] 파이프라인 시작 — alertId={}, alertName={}", alertId, alert.getAlertName());

        // Step 1: Verify
        VerificationResult verification = alertVerifier.verify(alert);
        alert.setVerificationStatus(verification.status().name());
        alertEventRepository.save(alert);
        log.info("[Chain] Step1 Verify — {}", verification.status());

        if (verification.status() == VerificationResult.Status.STALE) {
            log.info("[Chain] 알람 이미 해소 — 파이프라인 종료 alertId={}", alertId);
            return;
        }

        // Step 2: Playbook
        ActionRecommendation recommendation = alertPlaybook.lookup(alert.getAlertName());
        log.info("[Chain] Step2 Playbook — {} ({})", recommendation.description(), recommendation.category());

        // Step 3: Analyze
        AgentResult agentResult = runAgent(alert, recommendation);
        alert.setAnalysisResult(agentResult.conclusion());
        alert.setReasoningChain(agentResult.reasoningChain());
        alert.setAgentIterations(agentResult.iterationCount());
        alert.setReflectionResult(agentResult.reflectionResult());
        alertEventRepository.save(alert);
        log.info("[Chain] Step3 Analyze 완료 — alertId={}, toolCalls={}", alertId, agentResult.iterationCount());

        // Step 4: Authorize
        authorize(alert, agentResult, verification, recommendation);
        log.info("[Chain] Step4 Authorize 완료 — alertId={}, category={}", alertId, recommendation.category());
    }

    private AgentResult runAgent(AlertEvent alert, ActionRecommendation recommendation) {
        List<AlertEvent> recentConcurrent = alertEventRepository
                .findTop20ByResolvedFalseOrderByCreatedAtDesc()
                .stream()
                .filter(a -> !a.getId().equals(alert.getId()))
                .filter(a -> a.getCreatedAt().isAfter(Instant.now().minus(5, ChronoUnit.MINUTES)))
                .toList();

        if (recentConcurrent.size() >= ORCHESTRATOR_THRESHOLD) {
            log.info("[Chain] OrchestratorAgent 발동 — 동시 알람 {}개", recentConcurrent.size());
            return orchestratorAgent.orchestrate(alert, recentConcurrent);
        }
        return reActAgent.run(alert, recommendation);
    }

    private void authorize(AlertEvent alert, AgentResult agentResult,
                            VerificationResult verification, ActionRecommendation recommendation) {
        if (recommendation.category() == ActionRecommendation.Category.AUTO
                && recommendation.command() != null) {
            String cmd = resolveLabels(recommendation.command(), alert);
            log.info("[Chain] AUTO 실행: '{}'", cmd);
            CommandResult result = commandExecutorService.execute(cmd);
            discordNotificationService.sendAutoExecuted(
                    alert, agentResult.conclusion(), verification, recommendation, cmd, result);
        } else {
            discordNotificationService.sendAlert(
                    alert, agentResult.conclusion(), verification, recommendation);
        }
    }

    private String resolveLabels(String command, AlertEvent alert) {
        return AlertEvent.resolveTemplate(command, alert.getLabelsJson(), objectMapper);
    }
}
