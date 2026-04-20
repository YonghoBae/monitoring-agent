package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.playbook.ActionRecommendation;
import io.ohgnoy.monitoring.application.agent.tools.AgentTools;
import io.ohgnoy.monitoring.application.agent.tools.AgentToolsFactory;
import io.ohgnoy.monitoring.application.agent.ReActAgent;
import io.ohgnoy.monitoring.application.agent.ReflectionAdvisor;
import io.ohgnoy.monitoring.application.agent.tools.WebSearchTool;
import io.ohgnoy.monitoring.application.agent.AgentResult;
import io.ohgnoy.monitoring.application.agent.evaluation.AgentJudgeEvaluator;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.ObjectProvider;

import static io.ohgnoy.monitoring.domain.playbook.ActionRecommendation.Category.READ_ONLY;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("ReActAgent 단위 테스트")
class ReActAgentTest {

    @Mock AgentToolsFactory agentToolsFactory;
    @Mock WebSearchTool webSearchTool;
    @Mock AgentJudgeEvaluator judgeEvaluator;
    @Mock AgentTools agentTools;

    private final ActionRecommendation rec = new ActionRecommendation("확인", READ_ONLY, null);

    @SuppressWarnings("unchecked")
    private ObjectProvider<ChatClient> emptyProvider() {
        ObjectProvider<ChatClient> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(null);
        return provider;
    }

    @SuppressWarnings("unchecked")
    private ObjectProvider<ReflectionAdvisor> emptyReflectionProvider() {
        ObjectProvider<ReflectionAdvisor> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(null);
        return provider;
    }

    @Test
    @DisplayName("chatClient가 null이면 비활성화 메시지를 반환하고 도구 팩토리를 호출하지 않는다")
    void run_whenChatClientNull_returnsDisabledResult() {
        ReActAgent agent = new ReActAgent(
                emptyProvider(), emptyReflectionProvider(),
                agentToolsFactory, webSearchTool, judgeEvaluator);
        AlertEvent alert = new AlertEvent("WARNING", "CPU spike");

        AgentResult result = agent.run(alert, rec);

        assertThat(result.conclusion()).contains("비활성화");
        verifyNoInteractions(agentToolsFactory);
    }

    @Test
    @DisplayName("chatClient가 null이어도 judgeEvaluator.evaluate()는 항상 호출된다")
    void run_whenChatClientNull_stillCallsJudgeEvaluator() {
        ReActAgent agent = new ReActAgent(
                emptyProvider(), emptyReflectionProvider(),
                agentToolsFactory, webSearchTool, judgeEvaluator);
        AlertEvent alert = new AlertEvent("WARNING", "CPU spike");

        AgentResult result = agent.run(alert, rec);

        verify(judgeEvaluator).evaluate(eq(alert), eq(result));
    }
}
