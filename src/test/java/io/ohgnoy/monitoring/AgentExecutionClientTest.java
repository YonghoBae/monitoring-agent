package io.ohgnoy.monitoring;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import io.ohgnoy.monitoring.application.agent.AgentExecution;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.retry.support.RetryTemplate;

import java.net.InetSocketAddress;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.*;

class AgentExecutionClientTest {
    public static class ReadOnlyTool {
        final AtomicInteger reads = new AtomicInteger();
        @Tool(description = "Read a status value")
        public String read_status() { reads.incrementAndGet(); return "42"; }
    }

    @Test
    @Timeout(15)
    void actualSpringToolLoopStopsAtSharedBudgetAndDoesNotRepeatRead() throws Exception {
        var requests = new AtomicInteger();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/chat/completions", exchange -> {
            int request = requests.incrementAndGet();
            exchange.getRequestBody().readAllBytes();
            byte[] body = new ObjectMapper().writeValueAsBytes(Map.of(
                    "id", "chat-audit-" + request, "object", "chat.completion", "model", "fake",
                    "choices", List.of(Map.of("index", 0, "finish_reason", "tool_calls", "message", Map.of(
                            "role", "assistant", "content", "", "tool_calls", List.of(Map.of(
                                    "id", "call-" + request, "type", "function", "function", Map.of("name", "read_status", "arguments", "{}"))))))));
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        try {
            var model = OpenAiChatModel.builder().openAiApi(OpenAiApi.builder()
                    .baseUrl("http://127.0.0.1:" + server.getAddress().getPort()).apiKey("test").build())
                    .retryTemplate(RetryTemplate.builder().maxAttempts(1).build()).build();
            var execution = new AgentExecution(2, Duration.ofSeconds(10));
            var tool = new ReadOnlyTool();
            assertThatThrownBy(() -> execution.call(() -> ChatClient.builder(model).build().prompt()
                    .user("read status").toolCallbacks(execution.callbacks(tool)).call().content()))
                    .isInstanceOf(RuntimeException.class);
            assertThat(execution.callCount()).isEqualTo(2);
            assertThat(tool.reads).hasValue(1);
            assertThat(requests).hasValue(3);
            assertThat(execution.finish(null)).contains("호출 한도");
        } finally { server.stop(0); }
    }
}
