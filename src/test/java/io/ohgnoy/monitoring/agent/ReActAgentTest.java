package io.ohgnoy.monitoring.agent;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.service.ActionRecommendation;
import io.ohgnoy.monitoring.agent.service.agent.AgentTools;
import io.ohgnoy.monitoring.agent.service.agent.AgentToolsFactory;
import io.ohgnoy.monitoring.agent.service.agent.ReActAgent;
import io.ohgnoy.monitoring.agent.service.agent.ReflectionAgent;
import io.ohgnoy.monitoring.agent.service.agent.WebSearchTool;
import io.ohgnoy.monitoring.agent.service.agent.AgentResult;
import io.ohgnoy.monitoring.agent.service.evaluation.AgentJudgeEvaluator;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.prompt.Prompt;

import static io.ohgnoy.monitoring.agent.service.ActionRecommendation.Category.READ_ONLY;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("ReActAgent 단위 테스트")
class ReActAgentTest {

    @Mock AgentToolsFactory agentToolsFactory;
    @Mock WebSearchTool webSearchTool;
    @Mock ReflectionAgent reflectionAgent;
    @Mock AgentJudgeEvaluator judgeEvaluator;
    @Mock AgentTools agentTools;
    @Mock ChatModel chatModel;

    private final ActionRecommendation rec = new ActionRecommendation("확인", READ_ONLY, null);

    @Test
    @DisplayName("chatModel이 null이면 비활성화 메시지를 반환하고 도구 팩토리를 호출하지 않는다")
    void run_whenChatModelNull_returnsDisabledResult() {
        ReActAgent agent = new ReActAgent(null, agentToolsFactory, webSearchTool, reflectionAgent, judgeEvaluator);
        AlertEvent alert = new AlertEvent("WARNING", "CPU spike");

        AgentResult result = agent.run(alert, rec);

        assertThat(result.conclusion()).contains("비활성화");
        verifyNoInteractions(agentToolsFactory, reflectionAgent);
    }

    @Test
    @DisplayName("chatModel이 null이어도 judgeEvaluator.evaluate()는 항상 호출된다")
    void run_whenChatModelNull_stillCallsJudgeEvaluator() {
        ReActAgent agent = new ReActAgent(null, agentToolsFactory, webSearchTool, reflectionAgent, judgeEvaluator);
        AlertEvent alert = new AlertEvent("WARNING", "CPU spike");

        AgentResult result = agent.run(alert, rec);

        verify(judgeEvaluator).evaluate(eq(alert), eq(result));
    }

    @Test
    @DisplayName("chatModel이 예외를 던지면 에러 결론을 반환하고 judgeEvaluator를 호출한다")
    void run_whenChatModelThrows_returnsErrorResultAndCallsJudge() {
        when(agentToolsFactory.createAgentTools()).thenReturn(agentTools);
        when(agentTools.getReasoningLog()).thenReturn("");
        when(agentTools.getCallCount()).thenReturn(0);
        when(chatModel.call(any(Prompt.class))).thenThrow(new RuntimeException("Gemini API 오류"));

        ReActAgent agent = new ReActAgent(chatModel, agentToolsFactory, webSearchTool, reflectionAgent, judgeEvaluator);
        AlertEvent alert = new AlertEvent("ERROR", "database down");

        AgentResult result = agent.run(alert, rec);

        assertThat(result.conclusion()).contains("AI 분석 실패");
        assertThat(result.conclusion()).contains("Gemini API 오류");
        assertThat(result.iterationCount()).isZero();
        verify(judgeEvaluator).evaluate(eq(alert), any());
    }
}
