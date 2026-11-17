package io.ohgnoy.monitoring.infrastructure.command;

import io.ohgnoy.monitoring.infrastructure.command.CommandResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.List;
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

    public List<String> listContainers() {
        Process process = null;
        try {
            process = new ProcessBuilder("docker", "ps", "--format", "{{.Names}}")
                    .redirectErrorStream(true).start();
            if (!process.waitFor(5, TimeUnit.SECONDS)) {
                process.destroyForcibly();
                throw new IllegalStateException("Docker 컨테이너 목록 조회 시간 초과");
            }
            if (process.exitValue() != 0) throw new IllegalStateException("Docker 컨테이너 목록 조회 실패");
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()))) {
                return reader.lines()
                        .map(String::trim)
                        .filter(s -> !s.isBlank())
                        .toList();
            }
        } catch (IOException | InterruptedException e) {
            if (process != null) process.destroyForcibly();
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            log.warn("[CommandExecutorService] 컨테이너 목록 조회 실패: {}", e.getMessage());
            throw new IllegalStateException("Docker 컨테이너 목록 조회 실패", e);
        }
    }

    /** Read only selected fields; never return environment variables, labels or full inspect JSON. */
    public String inspectContainer(String name) {
        String format="{\"name\":{{json .Name}},\"image\":{{json .Config.Image}},\"status\":{{json .State.Status}},\"oomKilled\":{{json .State.OOMKilled}},\"exitCode\":{{json .State.ExitCode}},\"restartCount\":{{json .RestartCount}},\"health\":{{if .State.Health}}{{json .State.Health.Status}}{{else}}\"not_configured\"{{end}},\"ports\":{{json .NetworkSettings.Ports}}}";
        return inspectField(name,format);
    }
    public String containerLogPath(String name) {
        String path=inspectField(name,"{{.LogPath}}");
        if(path.isBlank()||!path.startsWith("/"))throw new IllegalStateException("Local container log path unavailable");
        return path;
    }
    private String inspectField(String name,String format) {
        if(name==null||!ALLOWED_CONTAINER_NAME.matcher(name).matches())throw new IllegalArgumentException("Invalid container name");
        Process process=null;
        try {
            process=new ProcessBuilder("docker","inspect","--type","container","--format",format,name).redirectErrorStream(true).start();
            final Process owned=process;
            var output=CompletableFuture.supplyAsync(()->{try{return owned.getInputStream().readNBytes(65537);}catch(IOException e){throw new java.io.UncheckedIOException(e);}});
            if(!process.waitFor(5,TimeUnit.SECONDS)){process.destroyForcibly();throw new IllegalStateException("Docker inspect timeout");}
            byte[] bytes=output.get(1,TimeUnit.SECONDS);
            if(process.exitValue()!=0)throw new IllegalStateException("Container details unavailable; target may be absent or Docker access failed");
            if(bytes.length>65536)throw new IllegalStateException("Container details exceed output limit");
            return new String(bytes,StandardCharsets.UTF_8).trim();
        }catch(Exception e){if(process!=null&&process.isAlive())process.destroyForcibly();if(e instanceof InterruptedException)Thread.currentThread().interrupt();throw new IllegalStateException("Container inspection failed",e);}
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
