package io.ohgnoy.monitoring.agent.service;

public record VerificationResult(
        Status status,
        String currentValue,  // Prometheus가 평가한 실제 값
        String activeAt       // 알람 발생 시각 (ISO8601)
) {
    public enum Status {
        CONFIRMED,  // 현재도 조건 유효 (Prometheus에서 firing 확인)
        STALE,      // 발생 후 조건 해소됨
        UNKNOWN     // 검증 불가 (Prometheus 오류 등)
    }

    public static VerificationResult confirmed(String value, String activeAt) {
        return new VerificationResult(Status.CONFIRMED, value, activeAt);
    }

    public static VerificationResult stale() {
        return new VerificationResult(Status.STALE, null, null);
    }

    public static VerificationResult unknown() {
        return new VerificationResult(Status.UNKNOWN, null, null);
    }

    public String toPromptLine() {
        return switch (status) {
            case CONFIRMED -> "CONFIRMED (현재값: " + currentValue + ", 발생: " + activeAt + ")";
            case STALE     -> "STALE — 알람 발생 당시 조건이 이미 해소됨";
            case UNKNOWN   -> "UNKNOWN — Prometheus 검증 불가";
        };
    }
}
