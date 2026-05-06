package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.infrastructure.discord.PendingApprovalStore;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PendingApprovalStoreTest {

    @Test
    void popByCommandReturnsStoredApproval() {
        PendingApprovalStore store = new PendingApprovalStore(30);

        store.store("docker restart app", 1L, "channel-1");

        assertThat(store.pop("docker restart app"))
                .hasValueSatisfying(approval -> {
                    assertThat(approval.alertId()).isEqualTo(1L);
                    assertThat(approval.channelId()).isEqualTo("channel-1");
                });
    }

    @Test
    void popByChannelReturnsStoredApproval() {
        PendingApprovalStore store = new PendingApprovalStore(30);

        store.store("docker restart app", 1L, "channel-1");

        assertThat(store.popByChannel("channel-1"))
                .hasValueSatisfying(approval ->
                        assertThat(approval.command()).isEqualTo("docker restart app"));
    }

    @Test
    void popByCommandRemovesChannelIndex() {
        PendingApprovalStore store = new PendingApprovalStore(30);

        store.store("docker restart app", 1L, "channel-1");
        store.pop("docker restart app");

        assertThat(store.popByChannel("channel-1")).isEmpty();
    }

    @Test
    void popByChannelRemovesCommandIndex() {
        PendingApprovalStore store = new PendingApprovalStore(30);

        store.store("docker restart app", 1L, "channel-1");
        store.popByChannel("channel-1");

        assertThat(store.pop("docker restart app")).isEmpty();
    }

    @Test
    void expiredApprovalIsNotReturned() {
        PendingApprovalStore store = new PendingApprovalStore(-1);

        store.store("docker restart app", 1L, "channel-1");

        assertThat(store.pop("docker restart app")).isEmpty();
        assertThat(store.popByChannel("channel-1")).isEmpty();
    }

    @Test
    void storingNewCommandForSameChannelReplacesPreviousCommand() {
        PendingApprovalStore store = new PendingApprovalStore(30);

        store.store("docker restart app-a", 1L, "channel-1");
        store.store("docker restart app-b", 2L, "channel-1");

        assertThat(store.pop("docker restart app-a")).isEmpty();
        assertThat(store.popByChannel("channel-1"))
                .hasValueSatisfying(approval -> {
                    assertThat(approval.command()).isEqualTo("docker restart app-b");
                    assertThat(approval.alertId()).isEqualTo(2L);
                });
    }
}
