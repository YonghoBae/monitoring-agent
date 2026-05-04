package io.ohgnoy.monitoring.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;

@Component
public class AlertWebhookAuthFilter extends OncePerRequestFilter {

    private static final String WEBHOOK_PATH = "/api/alerts/webhook";
    private static final String BEARER_PREFIX = "Bearer ";

    private final String expectedAuthorizationHeader;

    public AlertWebhookAuthFilter(
            @Value("${monitoring.webhook.token-file:}") String tokenFile) {
        if (tokenFile == null || tokenFile.isBlank()) {
            throw new IllegalStateException("monitoring.webhook.token-file must be set");
        }

        String token = readToken(tokenFile);
        if (token.isBlank()) {
            throw new IllegalStateException("monitoring webhook token file is empty: " + tokenFile);
        }
        this.expectedAuthorizationHeader = BEARER_PREFIX + token;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        String contextPath = request.getContextPath();
        if (contextPath != null && !contextPath.isBlank() && path.startsWith(contextPath)) {
            path = path.substring(contextPath.length());
        }
        return !("POST".equalsIgnoreCase(request.getMethod()) && WEBHOOK_PATH.equals(path));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String authorization = request.getHeader("Authorization");
        if (!matchesExpectedHeader(authorization)) {
            response.sendError(HttpServletResponse.SC_UNAUTHORIZED);
            return;
        }
        filterChain.doFilter(request, response);
    }

    private boolean matchesExpectedHeader(String authorization) {
        if (authorization == null) {
            return false;
        }
        byte[] actual = authorization.getBytes(StandardCharsets.UTF_8);
        byte[] expected = expectedAuthorizationHeader.getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(actual, expected);
    }

    private static String readToken(String tokenFile) {
        try {
            return Files.readString(Path.of(tokenFile), StandardCharsets.UTF_8).trim();
        } catch (IOException e) {
            throw new IllegalStateException("failed to read monitoring webhook token file: " + tokenFile, e);
        }
    }
}
