package io.ohgnoy.monitoring.agent.service;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.Collectors;

@Service
public class MonitoringAgentService {

    private final ChatModel chatModel;
    private final AlertVectorService alertVectorService;

    public MonitoringAgentService(
            @Qualifier("googleGenAiChatModel") @Nullable ChatModel chatModel,
            AlertVectorService alertVectorService
    ) {
        this.chatModel = chatModel;
        this.alertVectorService = alertVectorService;
    }

    public String buildAgentAnalysis(AlertEvent alert) {
        if (chatModel == null) {
            return "에이전트 분석 기능이 비활성화되어 기본 메시지만 전송합니다.";
        }

        List<Document> similar = alertVectorService.searchSimilar(alert.getMessage(), 5);

        String similarSummary = similar.isEmpty()
                ? "유사 알람이 아직 거의 없습니다."
                : similar.stream()
                        .map(doc -> "- " + doc.getText())
                        .collect(Collectors.joining("\n"));

        String promptText = """
                너는 인프라/서비스 모니터링 에이전트야.

                새로 발생한 알람:
                - 레벨: %s
                - 메시지: %s

                최근 유사 알람들:
                %s

                위 정보를 바탕으로:

                1) 이번 알람이 어떤 유형의 문제일 가능성이 높은지 한 줄로 요약해줘.
                2) 사람이 바로 시도해볼 수 있는 점검/조치 2~3가지를 bullet 리스트로 정리해줘.
                3) 심각도(낮음/보통/높음/치명적)도 같이 제안해줘.

                답변은 짧고 실용적으로, 한국어로 써.
                """.formatted(alert.getLevel(), alert.getMessage(), similarSummary);

        var prompt = new Prompt(new UserMessage(promptText));
        var response = chatModel.call(prompt);

        return response.getResult().getOutput().getText();
    }
}
