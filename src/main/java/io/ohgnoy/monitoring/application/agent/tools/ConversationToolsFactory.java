package io.ohgnoy.monitoring.application.agent.tools;

import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.discord.PendingApprovalStore;
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Component;

/**
 * ConversationTools 인스턴스 생성 팩토리.
 * AgentToolsFactory와 동일한 패턴으로 per-request 인스턴스를 생성한다.
 */
@Component
public class ConversationToolsFactory {

    private final CommandExecutorService commandExecutorService;
    private final PendingApprovalStore pendingApprovalStore;

    public ConversationToolsFactory(CommandExecutorService commandExecutorService,
                                    PendingApprovalStore pendingApprovalStore) {
        this.commandExecutorService = commandExecutorService;
        this.pendingApprovalStore = pendingApprovalStore;
    }

    public ConversationTools create(String channelId, @Nullable Long alertId) {
        return new ConversationTools(commandExecutorService, pendingApprovalStore, channelId, alertId);
    }
}
