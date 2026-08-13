package io.ohgnoy.monitoring.config;

import io.ohgnoy.monitoring.application.agent.ReflectionAdvisor;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Spring AI ChatClient 중앙 구성.
 *
 * @ConditionalOnBean 미사용 이유:
 * 사용자 @Configuration은 Spring AI 자동 구성보다 먼저 처리되므로
 * @ConditionalOnBean(name = "googleGenAiChatModel")이 항상 false로 평가된다.
 * ObjectProvider로 런타임에 빈 존재 여부를 확인한다.
 */
@Configuration
public class AgentConfig {

    @Bean
    ChatClient agentChatClient(@Qualifier("googleGenAiChatModel") ObjectProvider<ChatModel> googleChatModelProvider,
                               @Qualifier("openAiChatModel") ObjectProvider<ChatModel> openAiChatModelProvider,
                               @Value("${agent.provider:google}") String provider) {
        ChatModel chatModel = selectChatModel(provider, googleChatModelProvider, openAiChatModelProvider);
        if (chatModel == null) {
            return null;
        }
        return ChatClient.builder(chatModel).build();
    }

    @Bean
    ChatClient judgeChatClient(@Qualifier("googleGenAiChatModel") ObjectProvider<ChatModel> googleChatModelProvider,
                               @Qualifier("openAiChatModel") ObjectProvider<ChatModel> openAiChatModelProvider,
                               @Value("${judge.provider:google}") String provider,
                               @Value("${judge.model:}") String judgeModel) {
        ChatModel chatModel = selectChatModel(provider, googleChatModelProvider, openAiChatModelProvider);
        if (chatModel == null) {
            return null;
        }
        // Judge는 채점 기준(자)이므로 temperature 0으로 고정해 반복 측정 간 변동을 최소화한다.
        // judge.model 설정 시 에이전트와 다른 모델로 채점 — 같은 모델의 자기 응답 선호 편향 회피.
        ChatOptions.Builder options = ChatOptions.builder().temperature(0.0);
        if (judgeModel != null && !judgeModel.isBlank()) {
            options.model(judgeModel);
        }
        return ChatClient.builder(chatModel)
                .defaultOptions(options.build())
                .build();
    }

    @Bean
    ReflectionAdvisor reflectionAdvisor(@Qualifier("agentChatClient") ObjectProvider<ChatClient> chatClientProvider) {
        ChatClient chatClient = chatClientProvider.getIfAvailable();
        if (chatClient == null) {
            return null;
        }
        return new ReflectionAdvisor(chatClient);
    }

    private ChatModel selectChatModel(String provider,
                                      ObjectProvider<ChatModel> googleChatModelProvider,
                                      ObjectProvider<ChatModel> openAiChatModelProvider) {
        if ("openai".equalsIgnoreCase(provider)) {
            ChatModel openAi = openAiChatModelProvider.getIfAvailable();
            if (openAi != null) {
                return openAi;
            }
        }
        return googleChatModelProvider.getIfAvailable();
    }
}
