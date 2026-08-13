package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.application.agent.AgentResult;
import io.ohgnoy.monitoring.application.agent.ReActAgent;
import io.ohgnoy.monitoring.application.agent.ReflectionAdvisor;
import io.ohgnoy.monitoring.application.agent.evaluation.AgentJudgeEvaluator;
import io.ohgnoy.monitoring.application.agent.tools.AgentTools;
import io.ohgnoy.monitoring.application.agent.tools.AgentToolsFactory;
import io.ohgnoy.monitoring.application.agent.tools.WebSearchTool;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.playbook.ActionRecommendation;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.beans.factory.ObjectProvider;

import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static io.ohgnoy.monitoring.domain.playbook.ActionRecommendation.Category.READ_ONLY;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * ReflectionAdvisor가 ReAct 호출 체인에 실제로 연결되는지 검증하는 배선 테스트.
 * 라이브 평가에서 reflectionResult가 항상 비어 있는 문제의 회귀 방지용.
 */
@DisplayName("ReflectionAdvisor 배선 검증")
class ReflectionAdvisorWiringTest {

    /** 호출 횟수를 세는 스텁 ChatModel — 1차 호출(에이전트)과 2차 호출(reflection) 모두 처리 */
    static class StubChatModel implements ChatModel {
        final AtomicInteger calls = new AtomicInteger();

        @Override
        public ChatResponse call(Prompt prompt) {
            calls.incrementAndGet();
            String text = prompt.getContents().contains("SUFFICIENT")
                    ? "SUFFICIENT: 근거 충분"     // reflection 평가 응답
                    : "1) 근본 원인: 테스트 결론";  // 에이전트 결론
            return new ChatResponse(List.of(new Generation(new AssistantMessage(text))));
        }
    }

    @SuppressWarnings("unchecked")
    private static <T> ObjectProvider<T> providerOf(T value) {
        ObjectProvider<T> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(value);
        return provider;
    }

    @Test
    @DisplayName("ReActAgent.run() 실행 시 ReflectionAdvisor가 호출되어 reflectionResult가 채워진다")
    void reflectionAdvisor_isInvoked_andFillsReflectionResult() {
        StubChatModel stubModel = new StubChatModel();
        ChatClient chatClient = ChatClient.builder(stubModel).build();

        AgentToolsFactory factory = mock(AgentToolsFactory.class);
        AgentTools tools = mock(AgentTools.class);
        when(tools.getReasoningLog()).thenReturn("");   // 실제 구현은 null을 반환하지 않음
        when(factory.createAgentTools()).thenReturn(tools);

        AgentJudgeEvaluator noopJudge = mock(AgentJudgeEvaluator.class);
        ReflectionAdvisor reflectionAdvisor = new ReflectionAdvisor(chatClient);

        ReActAgent agent = new ReActAgent(
                providerOf(chatClient), providerOf(reflectionAdvisor),
                factory, mock(WebSearchTool.class), noopJudge, "v2");

        AlertEvent alert = new AlertEvent("WARNING", "test alert");
        AgentResult result = agent.run(alert, new ActionRecommendation("확인", READ_ONLY, null));

        assertThat(result.reflectionResult())
                .as("ReflectionAdvisor가 체인에서 실행되어 결과를 남겨야 한다")
                .isNotNull();
        assertThat(stubModel.calls.get())
                .as("에이전트 1회 + reflection 평가 1회 = 최소 2회 모델 호출")
                .isGreaterThanOrEqualTo(2);
    }
}
