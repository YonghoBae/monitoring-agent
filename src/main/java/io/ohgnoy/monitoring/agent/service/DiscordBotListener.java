package io.ohgnoy.monitoring.agent.service;

import io.ohgnoy.monitoring.agent.dto.CommandResult;
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

    public DiscordBotListener(
            @Value("${discord.bot.channel-id:}") String allowedChannelId,
            @Value("${discord.bot.allowed-role-id:}") String allowedRoleId,
            PendingApprovalStore pendingApprovalStore,
            CommandExecutorService commandExecutorService) {
        this.allowedChannelId = allowedChannelId;
        this.allowedRoleId = allowedRoleId;
        this.pendingApprovalStore = pendingApprovalStore;
        this.commandExecutorService = commandExecutorService;
    }

    @Override
    public void onMessageReceived(MessageReceivedEvent event) {
        if (event.getAuthor().isBot()) return;

        // 지정된 채널에서만 처리
        if (!allowedChannelId.isBlank() && !event.getChannel().getId().equals(allowedChannelId)) {
            return;
        }

        // 역할 권한 확인
        if (!allowedRoleId.isBlank() && !hasAllowedRole(event.getMember())) {
            return;
        }

        String content = event.getMessage().getContentRaw().trim();
        if (!content.startsWith("approve ")) return;

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

    private boolean hasAllowedRole(Member member) {
        if (member == null) return false;
        return member.getRoles().stream()
                .anyMatch(role -> role.getId().equals(allowedRoleId));
    }
}
