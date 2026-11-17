package io.ohgnoy.monitoring.application.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.support.ToolCallbacks;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.ai.tool.metadata.ToolMetadata;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.regex.Pattern;
import java.util.concurrent.*;
import java.util.function.Supplier;
import java.util.function.Consumer;

/** Request-scoped guard, shared by all tool families and reflection retries. */
public final class AgentExecution {
    private static final ObjectMapper JSON = new ObjectMapper().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    private static final ExecutorService REQUESTS = Executors.newVirtualThreadPerTaskExecutor();
    private static final Pattern APPROVAL_CLAIM = Pattern.compile("(?i)\\byes\\b|\\bno\\b|실행하시겠|재시작하시겠|명령.*제안|실제 실행 전.*확인|운영자.*확인");
    private static final Pattern COMMAND_REFERENCE = Pattern.compile("(?i)docker\\s+restart|execute_command");
    private final int maxCalls;
    private final Instant deadline;
    private final Clock clock;
    private final Clock observationClock;
    private final Consumer<ToolObservation> observationObserver;
    /** Exact callback response, after status wrapping; repeated cached deliveries are included. */
    public record ToolObservation(String tool, String input, String output) {}
    private final Map<String, String> cache = new HashMap<>();
    private final List<String> observations = new ArrayList<>();
    private int calls;
    private int unavailable;
    private String commandOutcome;
    private String pendingCommand;
    private String pendingReason;
    private volatile String stopReason;

    public AgentExecution(int maxCalls, Duration timeout) {
        this(maxCalls, timeout, Clock.systemUTC());
    }

    public AgentExecution(int maxCalls, Duration timeout, Clock clock) {
        this(maxCalls, timeout, clock, clock);
    }

    public AgentExecution(int maxCalls, Duration timeout, Clock clock, Clock observationClock) {
        this(maxCalls, timeout, clock, observationClock, observation -> {});
    }

    public AgentExecution(int maxCalls, Duration timeout, Clock clock, Clock observationClock,
                          Consumer<ToolObservation> observationObserver) {
        if (maxCalls < 1 || timeout.isNegative() || timeout.isZero()) throw new IllegalArgumentException("Invalid execution limits");
        this.maxCalls = maxCalls;
        this.clock = clock;
        this.observationClock = observationClock;
        this.observationObserver = Objects.requireNonNull(observationObserver);
        this.deadline = clock.instant().plus(timeout);
    }

    public ToolCallback[] callbacks(Object... objects) {
        return Arrays.stream(ToolCallbacks.from(objects)).map(this::wrap).toArray(ToolCallback[]::new);
    }

    public String call(Supplier<String> request) {
        ensureActive();
        Future<String> future = REQUESTS.submit(request::get);
        try {
            long remaining = Math.max(1, Duration.between(clock.instant(), deadline).toMillis());
            return future.get(remaining, TimeUnit.MILLISECONDS);
        } catch (TimeoutException e) {
            stopReason = "조사 시간 한도 도달";
            future.cancel(true);
            throw new Stopped(stopReason);
        } catch (InterruptedException e) {
            stopReason = "조사 중단";
            future.cancel(true);
            Thread.currentThread().interrupt();
            throw new Stopped(stopReason);
        } catch (ExecutionException e) {
            if (e.getCause() instanceof RuntimeException runtime) throw runtime;
            throw new IllegalStateException(e.getCause());
        }
    }

    public ToolCallback wrap(ToolCallback delegate) {
        return new ToolCallback() {
            public ToolDefinition getToolDefinition() { return delegate.getToolDefinition(); }
            public ToolMetadata getToolMetadata() {
                return getToolDefinition().name().equals("execute_command")
                        ? ToolMetadata.builder().returnDirect(true).build() : delegate.getToolMetadata();
            }
            public String call(String input) { return call(input, null); }
            public String call(String input, ToolContext context) {
                String response = invoke(delegate, input, context);
                observationObserver.accept(new ToolObservation(getToolDefinition().name(), input, response));
                return response;
            }
        };
    }

    private String invoke(ToolCallback delegate, String input, ToolContext context) {
        String name = delegate.getToolDefinition().name();
        String normalized = input;
        try { normalized = JSON.writeValueAsString(JSON.readValue(input, Object.class)); }
        catch (Exception ignored) { /* Invalid input is still counted and passed to validation. */ }
        String key = name + ":" + normalized;
        synchronized (this) {
            ensureActive();
            if (calls >= maxCalls) stop("도구 호출 한도 도달");
            calls++;
            if (cache.containsKey(key)) return cache.get(key);
        }
        String result;
        String status = "ok";
        try {
            result = delegate.call(input, context);
            // MethodToolCallback serializes Java String results as JSON string literals.
            if (result != null && result.startsWith("\"")) {
                try { result = JSON.readValue(result, String.class); }
                catch (Exception ignored) { /* Preserve a non-JSON legacy result. */ }
            }
            if (result == null || result.isBlank()) { result = "데이터 없음"; status = "empty"; }
            else if (name.equals("execute_command") && result.startsWith("PENDING_CONFIRM:")) {
                try {
                    var args = JSON.readTree(input);
                    pendingCommand = args.path("command").asText();
                    pendingReason = args.path("reason").asText();
                } catch (Exception e) { throw new IllegalArgumentException("Invalid command proposal", e); }
                if (pendingCommand.isBlank() || pendingReason.isBlank()) {
                    result = "거부됨: 승인할 명령과 이유를 확인하지 못했습니다.";
                    status = "denied";
                } else status = "pending_confirmation";
                commandOutcome = result;
            }
            else if (name.equals("execute_command") && result.startsWith("거부됨:")) { status = "denied"; commandOutcome = result; }
            else if ((name.equals("verify_alert") && result.startsWith("UNKNOWN"))
                    || ((name.equals("get_system_status") || name.equals("get_hardware_status")) && result.contains("조회 실패"))
                    || (name.equals("query_prometheus") && result.startsWith("Prometheus 조회 실패"))
                    || (name.equals("web_search") && (result.startsWith("웹 검색 실패") || result.startsWith("웹 검색 기능이 설정되지")))) status = "unavailable";
            else if (result.startsWith("잘못된") || result.startsWith("허용되지 않는") || result.startsWith("존재하지 않는 컨테이너")) status = "invalid_argument";
            else if (((name.equals("query_prometheus") || name.equals("get_system_status") || name.equals("get_hardware_status")) && result.contains("데이터 없음"))
                    || result.startsWith("로그 없음") || result.startsWith("검색 조건에 일치하는")
                    || result.equals("유사한 과거 사례 없음.") || result.equals("실행 중인 컨테이너 없음")) status = "empty";
            if ((name.equals("get_system_status") || name.equals("get_hardware_status"))
                    && (status.equals("empty") || status.equals("unavailable"))
                    && Pattern.compile("[0-9]+(?:\\.[0-9]+)?\\s*(?:GiB|MiB|%|B/s)").matcher(result).find()) status = "partial";
        } catch (RuntimeException e) {
            result = "도구 조회 실패: " + e.getClass().getSimpleName();
            status = "unavailable";
        }
        synchronized (this) {
            if (status.equals("unavailable")) unavailable++;
            observations.add(name + " " + input + " => [" + status + "] " + result);
        }
        String response;
        try {
            response = JSON.writeValueAsString(Map.of("status", status, "source", name,
                    "observed_at", observationClock.instant().toString(), "data", result));
        } catch (Exception e) {
            throw new IllegalStateException("Cannot serialize tool observation", e);
        }
        synchronized (this) { cache.put(key, response); }
        return response;
    }

    public synchronized void ensureActive() {
        if (commandOutcome != null) stop("명령 제안 결과 반환");
        if (stopReason != null) throw new Stopped(stopReason);
        if (!clock.instant().isBefore(deadline)) stop("조사 시간 한도 도달");
    }

    private void stop(String reason) {
        stopReason = reason;
        throw new Stopped(reason);
    }

    public synchronized boolean canContinue() {
        return commandOutcome == null && stopReason == null && calls < maxCalls && clock.instant().isBefore(deadline);
    }

    public synchronized int callCount() { return calls; }
    public synchronized String summary() { return String.join("\n", observations); }

    /** Approval wording is derived from a successful tool result, never model text. */
    public synchronized String finish(String answer) {
        if (commandOutcome != null) {
            if (commandOutcome.startsWith("PENDING_CONFIRM:")) return "명령 실행 제안: " + pendingCommand + "\n이유: " + pendingReason
                    + "\n실행하려면 'yes', 취소하려면 'no'로 답해 주세요.";
            return commandOutcome;
        }
        if (stopReason != null || (unavailable > 0 && unavailable == observations.size()) || answer == null || answer.isBlank()) {
            return partialResult(stopReason != null ? stopReason : "현재 상태 확인 불가");
        }
        return answer;
    }

    public synchronized String finishConversation(String answer) {
        String result = finish(answer);
        if (commandOutcome != null || answer == null || !result.equals(answer)) return result;
        boolean copiedCommand = answer.lines().anyMatch(this::isCopiedCommand);
        if (APPROVAL_CLAIM.matcher(answer).find() || copiedCommand) {
            if (observations.isEmpty()) return "실행 승인 요청이 등록되지 않았습니다. 실행 대상 컨테이너 이름과 허용 명령을 확인해 주세요.";
            String cleaned = answer.lines().filter(line -> !APPROVAL_CLAIM.matcher(line).find() && !isCopiedCommand(line))
                    .collect(java.util.stream.Collectors.joining("\n")).trim();
            return cleaned.isBlank() ? "실행 승인 요청이 등록되지 않았습니다. 실행 대상과 허용 명령을 확인해 주세요." : cleaned;
        }
        return answer;
    }

    private boolean isCopiedCommand(String line) {
        return COMMAND_REFERENCE.matcher(line).find() && observations.stream().anyMatch(source -> source.contains(line.trim()));
    }

    private String partialResult(String reason) {
        StringBuilder result = new StringBuilder(reason).append(". 확인되지 않은 항목은 정상으로 판정할 수 없습니다.");
        for (String observation : observations) result.append("\n- ").append(observation.length() > 600 ? observation.substring(0, 600) + "…" : observation);
        return result.toString();
    }

    public static final class Stopped extends RuntimeException {
        public Stopped(String message) { super(message); }
    }
}
