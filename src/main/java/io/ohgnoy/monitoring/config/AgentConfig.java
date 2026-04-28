package io.ohgnoy.monitoring.config;

import io.ohgnoy.monitoring.application.agent.ReflectionAdvisor;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
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
                               @Value("${judge.provider:google}") String provider) {
        ChatModel chatModel = selectChatModel(provider, googleChatModelProvider, openAiChatModelProvider);
        if (chatModel == null) {
            return null;
        }
        return ChatClient.builder(chatModel).build();
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
