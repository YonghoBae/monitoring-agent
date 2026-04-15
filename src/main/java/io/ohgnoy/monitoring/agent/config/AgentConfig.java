package io.ohgnoy.monitoring.agent.config;

import io.ohgnoy.monitoring.agent.service.agent.ReflectionAdvisor;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.ObjectProvider;
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
    ChatClient agentChatClient(@Qualifier("googleGenAiChatModel") ObjectProvider<ChatModel> chatModelProvider) {
        ChatModel chatModel = chatModelProvider.getIfAvailable();
        if (chatModel == null) {
            return null;
        }
        return ChatClient.builder(chatModel).build();
    }

    @Bean
    ReflectionAdvisor reflectionAdvisor(ObjectProvider<ChatClient> chatClientProvider) {
        ChatClient chatClient = chatClientProvider.getIfAvailable();
        if (chatClient == null) {
            return null;
        }
        return new ReflectionAdvisor(chatClient);
    }
}
