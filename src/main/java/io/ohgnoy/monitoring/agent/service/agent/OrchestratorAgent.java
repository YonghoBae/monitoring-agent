package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.service.ActionRecommendation;
import io.ohgnoy.monitoring.agent.service.AlertPlaybook;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
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

    private final ChatClient chatClient;
    private final ReActAgent reActAgent;
    private final AlertPlaybook alertPlaybook;

    public OrchestratorAgent(@Qualifier("googleGenAiChatModel") @Nullable ChatModel chatModel,
                              ReActAgent reActAgent,
                              AlertPlaybook alertPlaybook) {
        this.chatClient = chatModel != null ? ChatClient.builder(chatModel).build() : null;
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

        // 각 그룹의 대표 알람으로 ReAct 실행 (병렬 처리는 추후 개선 가능)
        AgentResult primaryResult = null;
        for (List<AlertEvent> group : groups) {
            AlertEvent representative = group.get(0);
            ActionRecommendation recommendation = alertPlaybook.lookup(representative.getAlertName());

            // 그룹 내 다른 알람 정보를 컨텍스트로 추가
            String groupContext = buildGroupContext(group);
            AgentResult result = reActAgent.runWithContext(representative, recommendation, groupContext);

            if (group.contains(primary)) {
                primaryResult = result;
            }

            log.info("[OrchestratorAgent] 그룹 분석 완료 — 대표알람={}, toolCalls={}",
                    representative.getAlertName(), result.iterationCount());
        }

        return primaryResult != null ? primaryResult
                : reActAgent.run(primary, alertPlaybook.lookup(primary.getAlertName()));
    }

    /**
     * Gemini를 이용해 알람들을 연관성 기반으로 그룹핑한다.
     */
    private List<List<AlertEvent>> decompose(List<AlertEvent> alerts) {
        if (chatClient == null || alerts.size() <= 1) {
            return List.of(alerts);
        }

        try {
            String prompt = buildDecompositionPrompt(alerts);
            String response = chatClient.prompt().user(prompt).call().content();
            return parseGroups(response, alerts);
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

        sb.append("\n응답은 반드시 다음 형식만 사용해 (다른 설명 없이):\n");
        sb.append("GROUP_0: 0,2,3\nGROUP_1: 1,4\n");
        return sb.toString();
    }

    private List<List<AlertEvent>> parseGroups(String response, List<AlertEvent> alerts) {
        List<List<AlertEvent>> groups = new ArrayList<>();

        for (String line : response.split("\n")) {
            line = line.trim();
            if (!line.startsWith("GROUP_")) continue;

            try {
                String indicesPart = line.substring(line.indexOf(":") + 1).trim();
                List<AlertEvent> group = Arrays.stream(indicesPart.split(","))
                        .map(String::trim)
                        .mapToInt(Integer::parseInt)
                        .filter(idx -> idx >= 0 && idx < alerts.size())
                        .mapToObj(alerts::get)
                        .collect(Collectors.toList());

                if (!group.isEmpty()) groups.add(group);
            } catch (Exception e) {
                log.warn("[OrchestratorAgent] 그룹 파싱 실패: {}", line);
            }
        }

        // 파싱 실패 시 전체를 단일 그룹으로
        return groups.isEmpty() ? List.of(alerts) : groups;
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
