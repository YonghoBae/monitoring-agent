package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.config.AlertWebhookAuthFilter;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class AlertWebhookAuthFilterTest {

    @TempDir
    Path tempDir;

    @Test
    void webhookPostWithValidBearerTokenPasses() throws Exception {
        AlertWebhookAuthFilter filter = filterWithToken("secret-token");
        MockHttpServletRequest request = webhookRequest();
        request.addHeader("Authorization", "Bearer secret-token");
        MockHttpServletResponse response = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(chain.getRequest()).isSameAs(request);
    }

    @Test
    void webhookPostWithoutBearerTokenIsRejected() throws Exception {
        AlertWebhookAuthFilter filter = filterWithToken("secret-token");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(webhookRequest(), response, new MockFilterChain());

        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void webhookPostWithWrongBearerTokenIsRejected() throws Exception {
        AlertWebhookAuthFilter filter = filterWithToken("secret-token");
        MockHttpServletRequest request = webhookRequest();
        request.addHeader("Authorization", "Bearer wrong-token");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());

        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void nonWebhookRequestDoesNotRequireBearerToken() throws Exception {
        AlertWebhookAuthFilter filter = filterWithToken("secret-token");
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/alerts/open");
        MockHttpServletResponse response = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(chain.getRequest()).isSameAs(request);
    }

    private AlertWebhookAuthFilter filterWithToken(String token) throws Exception {
        Path tokenFile = tempDir.resolve("alert-webhook-token");
        Files.writeString(tokenFile, token + "\n");
        return new AlertWebhookAuthFilter(tokenFile.toString());
    }

    private MockHttpServletRequest webhookRequest() {
        return new MockHttpServletRequest("POST", "/api/alerts/webhook");
    }
}
