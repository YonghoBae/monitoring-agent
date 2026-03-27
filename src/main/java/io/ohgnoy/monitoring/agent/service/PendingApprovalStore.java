package io.ohgnoy.monitoring.agent.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class PendingApprovalStore {

    public record PendingApproval(String command, Long alertId, Instant expiresAt, @org.springframework.lang.Nullable String channelId) {}

    private final ConcurrentHashMap<String, PendingApproval> store = new ConcurrentHashMap<>();
    private final long ttlMinutes;

    public PendingApprovalStore(
            @Value("${discord.bot.approval-ttl-minutes:30}") long ttlMinutes) {
        this.ttlMinutes = ttlMinutes;
    }

    public void store(String command, Long alertId) {
        Instant expiresAt = Instant.now().plusSeconds(ttlMinutes * 60);
        store.put(command, new PendingApproval(command, alertId, expiresAt, null));
    }

    public void store(String command, Long alertId, String channelId) {
        Instant expiresAt = Instant.now().plusSeconds(ttlMinutes * 60);
        store.put("channel:" + channelId, new PendingApproval(command, alertId, expiresAt, channelId));
    }

    public Optional<PendingApproval> pop(String command) {
        PendingApproval approval = store.remove(command);
        if (approval == null) return Optional.empty();
        if (approval.expiresAt().isBefore(Instant.now())) return Optional.empty();
        return Optional.of(approval);
    }

    public Optional<PendingApproval> popByChannel(String channelId) {
        PendingApproval approval = store.remove("channel:" + channelId);
        if (approval == null) return Optional.empty();
        if (approval.expiresAt().isBefore(Instant.now())) return Optional.empty();
        return Optional.of(approval);
    }

    @Scheduled(fixedRate = 60_000)
    public void cleanExpired() {
        Instant now = Instant.now();
        store.entrySet().removeIf(e -> e.getValue().expiresAt().isBefore(now));
    }
}
