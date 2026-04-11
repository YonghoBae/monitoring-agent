package io.ohgnoy.monitoring.agent.config;

import io.ohgnoy.monitoring.agent.service.agent.ReflectionAdvisor;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.DependsOn;

/**
 * Spring AI ChatClient 중앙 구성.
 *
 * 각 에이전트의 역할이 다르므로 ChatClient를 분리하여
 * defaultSystem 등 빌더 레벨 설정을 에이전트별로 관리한다.
 *
 * @ConditionalOnBean + @DependsOn으로 Spring AI 자동 구성 이후에 빈이 생성되도록 보장.
 */
@Configuration
public class AgentConfig {

    @Bean
    @DependsOn("googleGenAiChatModel")
    @ConditionalOnBean(name = "googleGenAiChatModel")
    ChatClient agentChatClient(@Qualifier("googleGenAiChatModel") ChatModel chatModel) {
        return ChatClient.builder(chatModel).build();
    }

    @Bean
    @ConditionalOnBean(ChatClient.class)
    ReflectionAdvisor reflectionAdvisor(ChatClient agentChatClient) {
        return new ReflectionAdvisor(agentChatClient);
    }
}
