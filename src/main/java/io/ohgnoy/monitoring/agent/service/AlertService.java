package io.ohgnoy.monitoring.agent.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.dto.AlertmanagerAlert;
import io.ohgnoy.monitoring.agent.dto.AlertmanagerWebhookPayload;
import io.ohgnoy.monitoring.agent.dto.CommandResult;
import io.ohgnoy.monitoring.agent.repository.AlertEventRepository;
import io.ohgnoy.monitoring.agent.service.agent.AgentResult;
import io.ohgnoy.monitoring.agent.service.agent.OrchestratorAgent;
import io.ohgnoy.monitoring.agent.service.agent.ReActAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

@Service
public class AlertService {

    private static final Logger log = LoggerFactory.getLogger(AlertService.class);

    private static final int ORCHESTRATOR_THRESHOLD = 3; // 동시 알람 N개 이상 시 Orchestrator 발동

    private final AlertEventRepository alertEventRepository;
    private final AlertVectorService alertVectorService;
    private final DiscordNotificationService discordNotificationService;
    private final ReActAgent reActAgent;
    private final OrchestratorAgent orchestratorAgent;
    private final AlertVerifier alertVerifier;
    private final AlertPlaybook alertPlaybook;
    private final CommandExecutorService commandExecutorService;
    private final ObjectMapper objectMapper;

    public AlertService(AlertEventRepository alertEventRepository,
                        AlertVectorService alertVectorService,
                        DiscordNotificationService discordNotificationService,
                        ReActAgent reActAgent,
                        OrchestratorAgent orchestratorAgent,
                        AlertVerifier alertVerifier,
                        AlertPlaybook alertPlaybook,
                        CommandExecutorService commandExecutorService,
                        ObjectMapper objectMapper) {
        this.alertEventRepository = alertEventRepository;
        this.alertVectorService = alertVectorService;
        this.discordNotificationService = discordNotificationService;
        this.reActAgent = reActAgent;
        this.orchestratorAgent = orchestratorAgent;
        this.alertVerifier = alertVerifier;
        this.alertPlaybook = alertPlaybook;
        this.commandExecutorService = commandExecutorService;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public AlertEvent createAlert(String level, String message) {
        AlertEvent alert = new AlertEvent(level, message);
        AlertEvent saved = alertEventRepository.save(alert);
        alertVectorService.indexAlert(saved);

        if (shouldNotify(level)) {
            runAgentPipeline(saved);
        }
        return saved;
    }

    @Transactional
    public void processWebhookPayload(AlertmanagerWebhookPayload payload) {
        for (AlertmanagerAlert alert : payload.getAlerts()) {
            try {
                if ("resolved".equals(alert.getStatus())) {
                    resolveMatchingAlerts(alert);
                } else {
                    createAlertFromWebhook(alert);
                }
            } catch (Exception e) {
                log.error("알람 처리 실패: {}", alert, e);
            }
        }
    }

    private AlertEvent createAlertFromWebhook(AlertmanagerAlert alert) {
        String alertName  = alert.getLabels().getOrDefault("alertname", "");
        String severity   = alert.getLabels().getOrDefault("severity", "warn").toUpperCase();
        String summary    = alert.getAnnotations() != null
                ? alert.getAnnotations().getOrDefault("summary", "") : "";
        String desc       = alert.getAnnotations() != null
                ? alert.getAnnotations().getOrDefault("description", "") : "";
        String message    = "[" + alertName + "] " + summary;
        String labelsJson = toSortedJson(alert.getLabels());

        AlertEvent event = new AlertEvent(severity, message,
                alertName, labelsJson, summary, desc,
                alert.getStartsAt(), alert.getGeneratorURL());
        AlertEvent saved = alertEventRepository.save(event);
        alertVectorService.indexAlert(saved);

        if (shouldNotify(severity)) {
            runAgentPipeline(saved);
        }
        return saved;
    }

    /**
     * ReAct 에이전트 파이프라인
     *
     * 1. Verify     — 알람이 실제로 유효한가? (Prometheus 재확인)
     * 2. ReAct      — Gemini가 도구를 스스로 선택하며 반복 추론
     *                 (verify_alert / query_prometheus / query_loki / search_rag / web_search)
     * 3. Authorize  — Playbook safety ceiling 적용 후 실행 또는 Discord 전송
     *
     * NOTE: 이 메서드는 @Transactional 메서드 내부에서 호출되므로 Gemini API 호출
     * 기간 동안 DB 커넥션이 유지된다. 커넥션 풀 여유가 있는 소규모 환경에서는
     * 문제없으나, 확장 시 @Async + 별도 트랜잭션으로 분리 필요.
     */
    private void runAgentPipeline(AlertEvent alert) {
        // Step 1: Verify
        log.info("[Agent] Step1 Verify — alertId={}, alertName={}", alert.getId(), alert.getAlertName());
        VerificationResult verification = alertVerifier.verify(alert);
        alert.setVerificationStatus(verification.status().name());
        log.info("[Agent] Verification: {}", verification.status());

        // Step 2: Playbook lookup (safety ceiling)
        ActionRecommendation recommendation = alertPlaybook.lookup(alert.getAlertName());
        log.info("[Agent] Playbook: {} ({})", recommendation.description(), recommendation.category());

        // Step 3: 동시 알람 확인 → Orchestrator 또는 단일 ReAct 실행
        List<AlertEvent> recentConcurrent = alertEventRepository
                .findTop20ByResolvedFalseOrderByCreatedAtDesc()
                .stream()
                .filter(a -> !a.getId().equals(alert.getId()))
                .filter(a -> a.getCreatedAt().isAfter(LocalDateTime.now().minusMinutes(5)))
                .toList();

        AgentResult agentResult;
        if (recentConcurrent.size() >= ORCHESTRATOR_THRESHOLD) {
            log.info("[Agent] OrchestratorAgent 발동 — 동시 알람 {}개", recentConcurrent.size());
            agentResult = orchestratorAgent.orchestrate(alert, recentConcurrent);
        } else {
            agentResult = reActAgent.run(alert, recommendation);
        }

        // 추론 결과 저장
        alert.setAnalysisResult(agentResult.conclusion());
        alert.setReasoningChain(agentResult.reasoningChain());
        alert.setAgentIterations(agentResult.iterationCount());
        alert.setReflectionResult(agentResult.reflectionResult());
        log.info("[Agent] ReAct 완료 — alertId={}, toolCalls={}", alert.getId(), agentResult.iterationCount());

        // Step 4: Authorize — AUTO는 즉시 실행, 나머지는 Discord 전송
        log.info("[Agent] Step4 Authorize — category={}", recommendation.category());
        if (recommendation.category() == ActionRecommendation.Category.AUTO
                && recommendation.command() != null) {
            String cmd = resolveLabels(recommendation.command(), alert);
            log.info("[Agent] AUTO 실행: '{}'", cmd);
            CommandResult result = commandExecutorService.execute(cmd);
            discordNotificationService.sendAutoExecuted(alert, agentResult.conclusion(), verification, recommendation, cmd, result);
        } else {
            discordNotificationService.sendAlert(alert, agentResult.conclusion(), verification, recommendation);
        }
    }

    @SuppressWarnings("unchecked")
    private String resolveLabels(String command, AlertEvent alert) {
        if (command == null || alert.getLabelsJson() == null || alert.getLabelsJson().isBlank()) {
            return command;
        }
        try {
            Map<String, String> labels = objectMapper.readValue(alert.getLabelsJson(), Map.class);
            for (Map.Entry<String, String> e : labels.entrySet()) {
                command = command.replace("{" + e.getKey() + "}", e.getValue());
            }
        } catch (Exception ignored) {}
        return command;
    }

    private void resolveMatchingAlerts(AlertmanagerAlert alert) {
        String alertName  = alert.getLabels().getOrDefault("alertname", "");
        String labelsJson = toSortedJson(alert.getLabels());
        List<AlertEvent> open = alertEventRepository
                .findByAlertNameAndLabelsJsonAndResolvedFalse(alertName, labelsJson);
        open.forEach(e -> {
            e.resolve();
            alertEventRepository.save(e);
        });
    }

    private String toSortedJson(Map<String, String> map) {
        try {
            return objectMapper.writeValueAsString(new TreeMap<>(map));
        } catch (JsonProcessingException e) {
            return "{}";
        }
    }

    @Transactional(readOnly = true)
    public List<AlertEvent> getRecentOpenAlerts() {
        return alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc();
    }

    private boolean shouldNotify(String level) {
        if (level == null) return false;
        String upper = level.toUpperCase();
        return "ERROR".equals(upper) || "CRITICAL".equals(upper) || "WARNING".equals(upper) || "WARN".equals(upper);
    }
}
