package io.ohgnoy.monitoring.application.agent.tools;

import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.discord.PendingApprovalStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.lang.Nullable;

/**
 * 대화형 에이전트 전용 도구.
 * AgentTools와 함께 ConversationAgent에 주입되며, 명령 실행 제안 기능을 추가한다.
 * Spring 빈이 아닌 per-request POJO (AgentTools와 동일 패턴).
 */
public class ConversationTools {

    private static final Logger log = LoggerFactory.getLogger(ConversationTools.class);

    private final CommandExecutorService commandExecutorService;
    private final PendingApprovalStore pendingApprovalStore;
    private final String channelId;
    @Nullable
    private final Long alertId;

    public ConversationTools(CommandExecutorService commandExecutorService,
                             PendingApprovalStore pendingApprovalStore,
                             String channelId,
                             @Nullable Long alertId) {
        this.commandExecutorService = commandExecutorService;
        this.pendingApprovalStore = pendingApprovalStore;
        this.channelId = channelId;
        this.alertId = alertId;
    }

    @Tool(description = "명령 실행을 제안한다. 실제 실행 전 운영자의 확인(yes/no)이 필요하다.")
    public String execute_command(
            @ToolParam(description = "실행할 명령어 (docker restart <container-name> 형식만 허용)") String command,
            @ToolParam(description = "이 명령이 필요한 이유") String reason) {
        log.info("[ConversationTool] execute_command 제안: '{}', 이유: {}", command, reason);

        if (!commandExecutorService.isAllowed(command)) {
            log.warn("[ConversationTool] 허용되지 않은 명령어 거부: '{}'", command);
            return "거부됨: 허가되지 않은 명령어입니다. 허용 형식: docker restart <container-name>";
        }

        pendingApprovalStore.store(command, alertId, channelId);
        log.info("[ConversationTool] 승인 대기 저장: command='{}', channelId={}", command, channelId);
        return "PENDING_CONFIRM: 운영자에게 실행 여부를 확인하세요. 운영자가 'yes'로 확인하면 실행됩니다.";
    }
}
