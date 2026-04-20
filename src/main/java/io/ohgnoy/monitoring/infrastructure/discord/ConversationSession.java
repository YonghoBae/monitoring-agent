package io.ohgnoy.monitoring.infrastructure.discord;

import org.springframework.ai.chat.memory.InMemoryChatMemoryRepository;
import org.springframework.ai.chat.memory.MessageWindowChatMemory;
import org.springframework.lang.Nullable;

import java.time.Instant;

public class ConversationSession {

    private final String channelId;
    @Nullable
    private final Long alertId;
    private final MessageWindowChatMemory chatMemory;
    private volatile Instant lastActivityAt;

    public ConversationSession(String channelId, @Nullable Long alertId) {
        this.channelId = channelId;
        this.alertId = alertId;
        this.lastActivityAt = Instant.now();
        this.chatMemory = MessageWindowChatMemory.builder()
                .chatMemoryRepository(new InMemoryChatMemoryRepository())
                .maxMessages(50)
                .build();
    }

    public String channelId() { return channelId; }

    @Nullable
    public Long alertId() { return alertId; }

    public MessageWindowChatMemory chatMemory() { return chatMemory; }

    public Instant lastActivityAt() { return lastActivityAt; }

    public void refreshActivity() { this.lastActivityAt = Instant.now(); }
}
