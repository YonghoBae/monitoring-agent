package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.application.agent.AgentExecution;
import io.ohgnoy.monitoring.application.agent.tools.ConversationTools;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.discord.PendingApprovalStore;
import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

class ConversationApprovalContractTest {
    @Test
    void deniedBlankReasonNeverLeavesExecutablePendingApproval() {
        var executor = mock(CommandExecutorService.class);
        when(executor.isAllowed("docker restart nginx")).thenReturn(true);
        var store = new PendingApprovalStore(30);
        var tools = new ConversationTools(executor, store, "approval-contract", null);
        var execution = new AgentExecution(12, Duration.ofMinutes(1));
        execution.callbacks(tools)[0].call("{\"command\":\"docker restart nginx\",\"reason\":\"\"}");
        assertThat(execution.finishConversation("승인 대기")).contains("거부").doesNotContain("yes");
        assertThat(store.popByChannel("approval-contract")).isEmpty();
        verify(executor, never()).execute(anyString());
    }

    @Test
    void approvalShowsExactlyTheStoredCommandAndReason() {
        var executor = mock(CommandExecutorService.class);
        when(executor.isAllowed("docker restart postgres")).thenReturn(true);
        var store = new PendingApprovalStore(30);
        var tools = new ConversationTools(executor, store, "approval-contract", null);
        var execution = new AgentExecution(12, Duration.ofMinutes(1));
        execution.callbacks(tools)[0].call("{\"command\":\"docker restart postgres\",\"reason\":\"운영자 요청\"}");
        assertThat(execution.finishConversation("docker restart nginx"))
                .contains("docker restart postgres", "운영자 요청", "yes", "no").doesNotContain("nginx");
        assertThat(store.popByChannel("approval-contract")).hasValueSatisfying(p -> assertThat(p.command()).isEqualTo("docker restart postgres"));
        verify(executor, never()).execute(anyString());
    }
}
