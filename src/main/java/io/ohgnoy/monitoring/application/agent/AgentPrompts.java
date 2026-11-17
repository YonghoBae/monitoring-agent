package io.ohgnoy.monitoring.application.agent;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;

final class AgentPrompts {
    private AgentPrompts() { }
    static String load(String name) {
        try (var input = AgentPrompts.class.getResourceAsStream("/prompts/" + name)) {
            if (input == null) throw new IllegalStateException("시스템 프롬프트 리소스 없음: " + name);
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) { throw new UncheckedIOException(e); }
    }
    static String common() { return load("agent-common.txt"); }
}
