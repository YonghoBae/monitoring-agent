package io.ohgnoy.monitoring;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import io.ohgnoy.monitoring.application.agent.ConversationAgent;
import io.ohgnoy.monitoring.application.agent.tools.*;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.discord.ConversationSession;
import io.ohgnoy.monitoring.infrastructure.discord.PendingApprovalStore;
import io.ohgnoy.monitoring.infrastructure.loki.LokiQueryService;
import io.ohgnoy.monitoring.infrastructure.prometheus.AlertVerifier;
import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.retry.support.RetryTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.net.InetSocketAddress;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

class ConversationDiscoveryToolsTest {
    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    @Timeout(15)
    @SuppressWarnings("unchecked")
    void optionalReadToolsReachTheActualConversationLoopWithoutCommandApproval(boolean enabled) throws Exception {
        var json = new ObjectMapper();
        var requests = new CopyOnWriteArrayList<JsonNode>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/chat/completions", exchange -> {
            requests.add(json.readTree(exchange.getRequestBody()));
            boolean callTool = enabled && requests.size() == 1;
            Map<String, Object> message = callTool
                    ? Map.of("role", "assistant", "content", "", "tool_calls", List.of(Map.of(
                        "id", "inspect-1", "type", "function", "function", Map.of(
                            "name", "inspect_container", "arguments", "{\"containerName\":\"example\"}"))))
                    : Map.of("role", "assistant", "content", "조회 완료");
            byte[] body = json.writeValueAsBytes(Map.of("id", "discovery-test", "object", "chat.completion",
                    "model", "fake", "choices", List.of(Map.of("index", 0,
                    "finish_reason", callTool ? "tool_calls" : "stop", "message", message))));
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body); exchange.close();
        });
        server.start();
        try {
            var model = OpenAiChatModel.builder().openAiApi(OpenAiApi.builder()
                    .baseUrl("http://127.0.0.1:" + server.getAddress().getPort()).apiKey("test").build())
                    .retryTemplate(RetryTemplate.builder().maxAttempts(1).build()).build();
            ObjectProvider<ChatClient> provider = mock(ObjectProvider.class);
            when(provider.getIfAvailable()).thenReturn(ChatClient.builder(model).build());
            var command = mock(CommandExecutorService.class);
            when(command.inspectContainer("example")).thenReturn("{\"status\":\"running\",\"health\":\"not_configured\"}");
            var pending = new PendingApprovalStore(30);
            var factory = new AgentToolsFactory(mock(AlertVerifier.class), mock(PrometheusQueryService.class),
                    mock(LokiQueryService.class), mock(AlertVectorService.class), command);
            var agent = new ConversationAgent(provider, factory, new ConversationToolsFactory(command, pending), mock(WebSearchTool.class));
            ReflectionTestUtils.setField(agent, "discoveryToolsEnabled", enabled);
            assertThat(agent.chat(new ConversationSession("discovery-test", null), "example 컨테이너 상태 알려줘"))
                    .isEqualTo("조회 완료");
            var names = new java.util.HashSet<String>();
            requests.getFirst().path("tools").forEach(tool -> names.add(tool.path("function").path("name").asText()));
            if (enabled) {
                assertThat(names).contains("inspect_container", "describe_metric", "read_container_logs");
                assertThat(requests).hasSize(2);
                assertThat(requests.get(1).path("messages").toString()).contains("not_configured", "running");
                verify(command).inspectContainer("example");
            } else {
                assertThat(names).doesNotContain("inspect_container", "describe_metric", "read_container_logs");
                verify(command, never()).inspectContainer(anyString());
            }
            verify(command, never()).execute(anyString());
            assertThat(pending.popByChannel("discovery-test")).isEmpty();
        } finally { server.stop(0); }
    }
}
