package io.ohgnoy.monitoring.agent.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.lang.Nullable;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class ConversationSessionStore {

    private static final Logger log = LoggerFactory.getLogger(ConversationSessionStore.class);

    private final ConcurrentHashMap<String, ConversationSession> sessions = new ConcurrentHashMap<>();
    private final long ttlMinutes;

    public ConversationSessionStore(
            @Value("${discord.bot.session-ttl-minutes:60}") long ttlMinutes) {
        this.ttlMinutes = ttlMinutes;
    }

    public ConversationSession getOrCreate(String channelId, @Nullable Long alertId) {
        ConversationSession session = sessions.get(channelId);
        if (session != null) {
            session.refreshActivity();
            log.debug("기존 세션 갱신: channelId={}", channelId);
            return session;
        }
        ConversationSession newSession = new ConversationSession(channelId, alertId);
        sessions.put(channelId, newSession);
        log.info("대화 세션 생성: channelId={}, alertId={}", channelId, alertId);
        return newSession;
    }

    public Optional<ConversationSession> get(String channelId) {
        ConversationSession session = sessions.get(channelId);
        if (session == null) return Optional.empty();
        if (isExpired(session)) {
            sessions.remove(channelId);
            log.info("만료 세션 제거: channelId={}", channelId);
            return Optional.empty();
        }
        return Optional.of(session);
    }

    public void refresh(String channelId) {
        ConversationSession session = sessions.get(channelId);
        if (session != null) session.refreshActivity();
    }

    public void remove(String channelId) {
        sessions.remove(channelId);
        log.info("세션 종료: channelId={}", channelId);
    }

    @Scheduled(fixedRate = 60_000)
    public void cleanExpired() {
        Instant cutoff = Instant.now().minusSeconds(ttlMinutes * 60);
        sessions.entrySet().removeIf(e -> {
            boolean expired = e.getValue().lastActivityAt().isBefore(cutoff);
            if (expired) log.info("세션 만료 제거: channelId={}", e.getKey());
            return expired;
        });
    }

    private boolean isExpired(ConversationSession session) {
        return session.lastActivityAt().isBefore(Instant.now().minusSeconds(ttlMinutes * 60));
    }
}
