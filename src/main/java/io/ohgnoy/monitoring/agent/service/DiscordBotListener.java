package io.ohgnoy.monitoring.agent.service;

import io.ohgnoy.monitoring.agent.dto.CommandResult;
import io.ohgnoy.monitoring.agent.service.agent.ConversationAgent;
import net.dv8tion.jda.api.entities.Member;
import net.dv8tion.jda.api.events.message.MessageReceivedEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "discord.bot.token")
public class DiscordBotListener extends ListenerAdapter {

    private static final Logger log = LoggerFactory.getLogger(DiscordBotListener.class);

    private final String allowedChannelId;
    private final String allowedRoleId;
    private final PendingApprovalStore pendingApprovalStore;
    private final CommandExecutorService commandExecutorService;
    private final ResolutionFeedbackService resolutionFeedbackService;
    private final ConversationAgent conversationAgent;
    private final ConversationSessionStore sessionStore;

    public DiscordBotListener(
            @Value("${discord.bot.channel-id:}") String allowedChannelId,
            @Value("${discord.bot.allowed-role-id:}") String allowedRoleId,
            PendingApprovalStore pendingApprovalStore,
            CommandExecutorService commandExecutorService,
            ResolutionFeedbackService resolutionFeedbackService,
            ConversationAgent conversationAgent,
            ConversationSessionStore sessionStore) {
        this.allowedChannelId = allowedChannelId;
        this.allowedRoleId = allowedRoleId;
        this.pendingApprovalStore = pendingApprovalStore;
        this.commandExecutorService = commandExecutorService;
        this.resolutionFeedbackService = resolutionFeedbackService;
        this.conversationAgent = conversationAgent;
        this.sessionStore = sessionStore;
    }

    @Override
    public void onMessageReceived(MessageReceivedEvent event) {
        if (event.getAuthor().isBot()) return;

        log.debug("[DiscordBot] 메시지 수신: channel={}, user={}, content={}",
                event.getChannel().getId(), event.getAuthor().getName(),
                event.getMessage().getContentRaw());

        if (!allowedChannelId.isBlank() && !event.getChannel().getId().equals(allowedChannelId)) {
            log.debug("[DiscordBot] 채널 불일치 무시: 수신={}, 허용={}", event.getChannel().getId(), allowedChannelId);
            return;
        }

        if (!allowedRoleId.isBlank() && !hasAllowedRole(event.getMember())) {
            log.debug("[DiscordBot] Role 불일치 무시: user={}", event.getAuthor().getName());
            return;
        }

        String content = event.getMessage().getContentRaw().trim();
        String channelId = event.getChannel().getId();

        // 우선순위 순 라우팅
        if (content.startsWith("resolved ") || content.startsWith("false-positive ")) {
            handleFeedback(event, content);
            return;
        }

        if (content.startsWith("approve ")) {
            handleApprove(event, content);
            return;
        }

        if (content.equalsIgnoreCase("yes") || content.equals("확인")) {
            handleYes(event, channelId);
            return;
        }

        if (content.equalsIgnoreCase("no") || content.equals("취소")) {
            handleNo(event, channelId);
            return;
        }

        handleConversation(event, channelId, content);
    }

    private void handleApprove(MessageReceivedEvent event, String content) {
        String command = content.substring("approve ".length()).trim();
        log.info("Approve 명령 수신: '{}' by {}", command, event.getAuthor().getName());

        pendingApprovalStore.pop(command).ifPresentOrElse(
                approval -> {
                    CommandResult result = commandExecutorService.execute(command);
                    String reply = result.isSuccess()
                            ? "✅ 실행 완료: `" + command + "`\n```\n" + result.output().trim() + "\n```"
                            : "❌ 실행 실패 (exit " + result.exitCode() + "): `" + command + "`\n```\n"
                                    + result.errorOutput().trim() + "\n```";
                    event.getChannel().sendMessage(reply).queue();
                },
                () -> event.getChannel().sendMessage(
                        "❌ 대기 중인 승인 요청 없음 (만료 또는 미존재): `" + command + "`"
                ).queue()
        );
    }

    private void handleYes(MessageReceivedEvent event, String channelId) {
        log.info("Yes 확인 수신: channelId={}, by {}", channelId, event.getAuthor().getName());

        pendingApprovalStore.popByChannel(channelId).ifPresentOrElse(
                approval -> {
                    CommandResult result = commandExecutorService.execute(approval.command());
                    String reply = result.isSuccess()
                            ? "✅ 실행 완료: `" + approval.command() + "`\n```\n" + result.output().trim() + "\n```"
                            : "❌ 실행 실패 (exit " + result.exitCode() + "): `" + approval.command() + "`\n```\n"
                                    + result.errorOutput().trim() + "\n```";
                    event.getChannel().sendMessage(reply).queue();
                    sessionStore.refresh(channelId);
                },
                () -> event.getChannel().sendMessage("대기 중인 명령어가 없습니다.").queue()
        );
    }

    private void handleNo(MessageReceivedEvent event, String channelId) {
        log.info("No 취소 수신: channelId={}, by {}", channelId, event.getAuthor().getName());

        pendingApprovalStore.popByChannel(channelId).ifPresentOrElse(
                approval -> event.getChannel().sendMessage(
                        "취소했습니다: `" + approval.command() + "`"
                ).queue(),
                () -> event.getChannel().sendMessage("대기 중인 명령어가 없습니다.").queue()
        );
    }

    private void handleConversation(MessageReceivedEvent event, String channelId, String content) {
        log.info("대화 메시지 수신: channelId={}, by {}", channelId, event.getAuthor().getName());

        ConversationSession session = sessionStore.get(channelId)
                .orElseGet(() -> sessionStore.getOrCreate(channelId, null));

        String response = conversationAgent.chat(session, content);
        sendLongMessage(event, response);
        sessionStore.refresh(channelId);
    }

    private void sendLongMessage(MessageReceivedEvent event, String text) {
        if (text == null || text.isBlank()) return;
        int limit = 1990;
        int start = 0;
        while (start < text.length()) {
            int end = Math.min(start + limit, text.length());
            event.getChannel().sendMessage(text.substring(start, end)).queue();
            start = end;
        }
    }

    private void handleFeedback(MessageReceivedEvent event, String content) {
        String[] parts = content.split("\\s+", 3);
        String cmd = parts[0];

        if (parts.length < 2) {
            event.getChannel().sendMessage(
                    "사용법: `" + cmd + " <alertId> [해결 방법 설명]`"
            ).queue();
            return;
        }

        try {
            long alertId = Long.parseLong(parts[1]);
            String note = parts.length > 2 ? parts[2] : "";
            String outcome = "resolved".equals(cmd) ? "RESOLVED" : "FALSE_POSITIVE";

            log.info("[DiscordBot] 피드백 수신: {} alertId={} by {}", outcome, alertId, event.getAuthor().getName());
            String reply = resolutionFeedbackService.recordOutcome(alertId, outcome, note);
            event.getChannel().sendMessage(reply).queue();
        } catch (NumberFormatException e) {
            event.getChannel().sendMessage("❌ 잘못된 alertId: `" + parts[1] + "`").queue();
        }
    }

    private boolean hasAllowedRole(Member member) {
        if (member == null) return false;
        return member.getRoles().stream()
                .anyMatch(role -> role.getId().equals(allowedRoleId));
    }
}
