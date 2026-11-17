package io.ohgnoy.monitoring;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.application.agent.ConversationAgent;
import io.ohgnoy.monitoring.application.agent.tools.*;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.discord.ConversationSession;
import io.ohgnoy.monitoring.infrastructure.discord.PendingApprovalStore;
import io.ohgnoy.monitoring.infrastructure.loki.LokiQueryService;
import io.ohgnoy.monitoring.infrastructure.prometheus.AlertVerifier;
import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.retry.support.RetryTemplate;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

/** Live model + real Prometheus; command execution and external messaging are absent. */
@Tag("eval")
@EnabledIfEnvironmentVariable(named = "OLLAMA_ROUTER_SMOKE_URL", matches = "https?://.+")
class HardwareConversationLiveSmokeTest {
    @Test
    @Timeout(90)
    @SuppressWarnings("unchecked")
    void ramAndGpuQuestionQueriesActualMetrics() {
        var model = OpenAiChatModel.builder()
                .openAiApi(OpenAiApi.builder().baseUrl(System.getenv("OLLAMA_ROUTER_SMOKE_URL")).apiKey("ollama").build())
                .defaultOptions(OpenAiChatOptions.builder().model("qwen3:8b").reasoningEffort("none")
                        .maxTokens(512).temperature(0.0).build())
                .retryTemplate(RetryTemplate.builder().maxAttempts(1).build()).build();
        ObjectProvider<ChatClient> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(ChatClient.builder(model).build());
        var prometheus = new PrometheusQueryService(RestClient.builder(),
                System.getenv().getOrDefault("PROMETHEUS_SMOKE_URL", "http://localhost:9090"), new ObjectMapper());
        CommandExecutorService executor = mock(CommandExecutorService.class);
        AgentTools tools = new AgentTools(mock(AlertVerifier.class), prometheus,
                mock(LokiQueryService.class), mock(AlertVectorService.class), executor);
        AgentToolsFactory factory = mock(AgentToolsFactory.class);
        when(factory.createAgentTools()).thenReturn(tools);
        var agent = new ConversationAgent(provider, factory,
                new ConversationToolsFactory(executor, mock(PendingApprovalStore.class)), mock(WebSearchTool.class));
        String answer = agent.chat(new ConversationSession("hardware-live-smoke", null), "램이랑 gpu는?");
        assertThat(tools.getReasoningLog()).contains("get_hardware_status", "RAM", "GPU", "GiB", "MiB");
        assertThat(answer).doesNotContain("수집되지", "메트릭이 없습니다", "오류가 발생했습니다");
        verifyNoInteractions(executor);
        System.out.println("HARDWARE_CONVERSATION_SMOKE_PASS\n" + answer);
    }
}
