package io.ohgnoy.monitoring.infrastructure.discord;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class PendingApprovalStore {

    public record PendingApproval(String command, Long alertId, Instant expiresAt, @org.springframework.lang.Nullable String channelId) {}

    private final ConcurrentHashMap<String, PendingApproval> byCommand = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, String> commandByChannel = new ConcurrentHashMap<>();
    private final long ttlMinutes;

    public PendingApprovalStore(
            @Value("${discord.bot.approval-ttl-minutes:30}") long ttlMinutes) {
        this.ttlMinutes = ttlMinutes;
    }

    public void store(String command, Long alertId, String channelId) {
        Instant expiresAt = Instant.now().plusSeconds(ttlMinutes * 60);
        PendingApproval approval = new PendingApproval(command, alertId, expiresAt, normalizeChannelId(channelId));
        PendingApproval previousApproval = byCommand.put(command, approval);
        if (previousApproval != null && previousApproval.channelId() != null) {
            commandByChannel.remove(previousApproval.channelId(), previousApproval.command());
        }
        if (approval.channelId() != null) {
            String previousCommand = commandByChannel.put(approval.channelId(), command);
            if (previousCommand != null && !previousCommand.equals(command)) {
                byCommand.remove(previousCommand);
            }
        }
    }

    public Optional<PendingApproval> pop(String command) {
        PendingApproval approval = byCommand.remove(command);
        if (approval == null) return Optional.empty();
        if (approval.channelId() != null) {
            commandByChannel.remove(approval.channelId(), command);
        }
        if (approval.expiresAt().isBefore(Instant.now())) {
            return Optional.empty();
        }
        return Optional.of(approval);
    }

    public Optional<PendingApproval> popByChannel(String channelId) {
        String normalizedChannelId = normalizeChannelId(channelId);
        if (normalizedChannelId == null) return Optional.empty();
        String command = commandByChannel.remove(normalizedChannelId);
        if (command == null) return Optional.empty();
        return pop(command);
    }

    @Scheduled(fixedRate = 60_000)
    public void cleanExpired() {
        Instant now = Instant.now();
        byCommand.entrySet().removeIf(e -> {
            PendingApproval approval = e.getValue();
            boolean expired = approval.expiresAt().isBefore(now);
            if (expired && approval.channelId() != null) {
                commandByChannel.remove(approval.channelId(), approval.command());
            }
            return expired;
        });
    }

    private static String normalizeChannelId(String channelId) {
        if (channelId == null || channelId.isBlank()) {
            return null;
        }
        return channelId;
    }
}
