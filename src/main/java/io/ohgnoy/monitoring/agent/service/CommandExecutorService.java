package io.ohgnoy.monitoring.agent.service;

import io.ohgnoy.monitoring.agent.dto.CommandResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

@Service
public class CommandExecutorService {

    private static final Logger log = LoggerFactory.getLogger(CommandExecutorService.class);

    // 허용 패턴: docker restart <container-name>
    private static final Pattern ALLOWED_CONTAINER_NAME =
            Pattern.compile("^[a-zA-Z0-9][a-zA-Z0-9_.\\-]*$");

    public boolean isAllowed(String command) {
        String[] parts = command.trim().split("\\s+");
        return parts.length == 3
                && "docker".equals(parts[0])
                && "restart".equals(parts[1])
                && ALLOWED_CONTAINER_NAME.matcher(parts[2]).matches();
    }

    public CommandResult execute(String command) {
        if (!isAllowed(command)) {
            return new CommandResult(-1, "", "허용되지 않는 명령어 형식: " + command);
        }

        String containerName = command.trim().split("\\s+")[2];

        log.info("Executing: docker restart {}", containerName);
        try {
            ProcessBuilder pb = new ProcessBuilder("docker", "restart", containerName);
            Process process = pb.start();

            // deadlock 방지를 위해 stdout/stderr 동시 읽기
            CompletableFuture<String> stdoutFuture = CompletableFuture.supplyAsync(() -> {
                try { return new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8); }
                catch (IOException e) { return ""; }
            });
            CompletableFuture<String> stderrFuture = CompletableFuture.supplyAsync(() -> {
                try { return new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8); }
                catch (IOException e) { return ""; }
            });

            boolean finished = process.waitFor(30, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                return new CommandResult(-1, stdoutFuture.getNow(""), "명령어 타임아웃 (30초)");
            }

            return new CommandResult(process.exitValue(), stdoutFuture.join(), stderrFuture.join());

        } catch (IOException | InterruptedException e) {
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            log.error("명령어 실행 실패: {}", command, e);
            return new CommandResult(-1, "", "실행 오류: " + e.getMessage());
        }
    }
}
