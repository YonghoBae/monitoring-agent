package io.ohgnoy.monitoring;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.retry.support.RetryTemplate;

import static org.assertj.core.api.Assertions.assertThat;

/** Explicit read-only smoke test using the exact Spring AI client used by the app. */
@Tag("eval")
@EnabledIfEnvironmentVariable(named = "OLLAMA_ROUTER_SMOKE_URL", matches = "https?://.+")
class OllamaRouterSpringClientSmokeTest {
    @Test
    void springAiClientCanSendCompletionToLiveRouter() {
        OpenAiChatModel model = OpenAiChatModel.builder()
                .openAiApi(OpenAiApi.builder().baseUrl(System.getenv("OLLAMA_ROUTER_SMOKE_URL")).apiKey("ollama").build())
                .defaultOptions(OpenAiChatOptions.builder().model("qwen3:8b")
                        .reasoningEffort("none").maxTokens(32).temperature(0.0).build())
                .retryTemplate(RetryTemplate.builder().maxAttempts(1).build())
                .build();
        var response = model.call(new Prompt("Reply with one word: OK"));
        assertThat(response.getResult().getOutput().getText()).isNotBlank();
        System.out.println("SPRING_ROUTER_SMOKE_PASS model=" + response.getMetadata().getModel());
    }
}
