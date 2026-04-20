package io.ohgnoy.monitoring.application.agent;

import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.playbook.ActionRecommendation;
import io.ohgnoy.monitoring.domain.playbook.AlertPlaybook;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

/**
 * 복합 알람 상황에서 Task Decomposition을 수행하는 오케스트레이터.
 *
 * 최근 5분 내 동시 알람이 3개 이상일 때 발동한다.
 * Gemini가 알람 간 연관성을 판단해 독립적인 서브태스크로 분리하고,
 * 각 서브태스크를 ReActAgent가 독립적으로 분석한다.
 */
@Service
public class OrchestratorAgent {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorAgent.class);
    private static final long AGENT_TIMEOUT_SECONDS = 120;

    private final ChatClient chatClient;
    private final ReActAgent reActAgent;
    private final AlertPlaybook alertPlaybook;
    private final ExecutorService agentExecutor = Executors.newVirtualThreadPerTaskExecutor();

    public OrchestratorAgent(ObjectProvider<ChatClient> chatClientProvider,
                              ReActAgent reActAgent,
                              AlertPlaybook alertPlaybook) {
        this.chatClient = chatClientProvider.getIfAvailable();
        this.reActAgent = reActAgent;
        this.alertPlaybook = alertPlaybook;
    }

    /**
     * 복합 알람을 분해하여 각각 분석한 후 대표 AlertEvent에 대한 결과를 반환한다.
     *
     * @param primary  주 알람 (현재 처리 중인 AlertEvent)
     * @param concurrent 최근 동시 발생 알람 목록
     * @return 주 알람에 대한 AgentResult (다른 그룹 결과는 로그에만 기록)
     */
    public AgentResult orchestrate(AlertEvent primary, List<AlertEvent> concurrent) {
        List<AlertEvent> all = new ArrayList<>();
        all.add(primary);
        all.addAll(concurrent);

        log.info("[OrchestratorAgent] 복합 알람 분해 시작 — {}개 알람", all.size());

        // Gemini로 알람 그룹핑
        List<List<AlertEvent>> groups = decompose(all);
        log.info("[OrchestratorAgent] {} 그룹으로 분해됨", groups.size());

        // 주 알람이 속한 그룹 찾기
        List<AlertEvent> primaryGroup = groups.stream()
                .filter(g -> g.contains(primary))
                .findFirst()
                .orElse(List.of(primary));

        // 각 그룹을 병렬로 ReAct 실행 (Virtual Thread — I/O 바운드 LLM 호출에 최적)
        List<CompletableFuture<AgentResult>> futures = groups.stream()
                .map(group -> CompletableFuture.supplyAsync(() -> {
                    AlertEvent representative = group.get(0);
                    ActionRecommendation recommendation = alertPlaybook.lookup(representative.getAlertName());
                    AgentResult result = reActAgent.runWithContext(representative, recommendation, buildGroupContext(group));
                    log.info("[OrchestratorAgent] 그룹 분석 완료 — 대표알람={}, toolCalls={}",
                            representative.getAlertName(), result.iterationCount());
                    return result;
                }, agentExecutor).orTimeout(AGENT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
                .toList();

        // 모든 그룹 완료 대기
        List<AgentResult> results = futures.stream()
                .map(CompletableFuture::join)
                .toList();

        // 주 알람이 속한 그룹의 결과 반환
        for (int i = 0; i < groups.size(); i++) {
            if (groups.get(i).contains(primary)) {
                return results.get(i);
            }
        }

        return reActAgent.run(primary, alertPlaybook.lookup(primary.getAlertName()));
    }

    private record GroupingResult(List<List<Integer>> groups) {}

    /**
     * Gemini를 이용해 알람들을 연관성 기반으로 그룹핑한다.
     * Structured Output으로 파싱 실패 가능성을 없앤다.
     */
    private List<List<AlertEvent>> decompose(List<AlertEvent> alerts) {
        if (chatClient == null || alerts.size() <= 1) {
            return List.of(alerts);
        }

        try {
            GroupingResult result = chatClient.prompt()
                    .system("너는 인프라 알람 분류 전문가야. 주어진 알람들을 연관성 기반으로 그룹핑해. 응답은 반드시 JSON 형식으로만 해.")
                    .user(buildDecompositionPrompt(alerts))
                    .call()
                    .entity(GroupingResult.class);

            if (result == null || result.groups() == null || result.groups().isEmpty()) {
                return List.of(alerts);
            }

            List<List<AlertEvent>> groups = result.groups().stream()
                    .map(indices -> indices.stream()
                            .filter(idx -> idx >= 0 && idx < alerts.size())
                            .map(alerts::get)
                            .collect(Collectors.toList()))
                    .filter(g -> !g.isEmpty())
                    .collect(Collectors.toList());

            return groups.isEmpty() ? List.of(alerts) : groups;

        } catch (Exception e) {
            log.warn("[OrchestratorAgent] 분해 실패, 단일 그룹으로 처리: {}", e.getMessage());
            return List.of(alerts);
        }
    }

    private String buildDecompositionPrompt(List<AlertEvent> alerts) {
        StringBuilder sb = new StringBuilder();
        sb.append("다음 알람들을 분석해서 독립적인 하위 작업으로 분류해줘.\n\n");
        sb.append("같은 컨테이너, 같은 호스트, 연쇄 장애로 보이는 알람은 하나의 그룹으로 묶어.\n");
        sb.append("독립적인 알람은 별도 그룹으로 분리해.\n\n");

        for (int i = 0; i < alerts.size(); i++) {
            AlertEvent a = alerts.get(i);
            sb.append(i).append(". [").append(a.getAlertName()).append("] ")
                    .append(a.getMessage()).append(" labels=").append(a.getLabelsJson()).append("\n");
        }

        return sb.toString();
    }

    private String buildGroupContext(List<AlertEvent> group) {
        if (group.size() <= 1) return "";

        return "\n[동시 발생 관련 알람 — 같은 그룹으로 분류됨]\n" +
                group.stream()
                        .skip(1)
                        .map(a -> "- [" + a.getAlertName() + "] " + a.getMessage())
                        .collect(Collectors.joining("\n"))
                + "\n(위 알람들과 연관성을 고려해서 분석해.)\n";
    }
}
