package io.ohgnoy.monitoring.application.agent.evaluation;

import java.util.List;

public record JudgeEvaluationResult(
        DimensionScore factuality,
        DimensionScore tool_use,
        DimensionScore actionability,
        DimensionScore safety,
        String verdict,
        List<String> missing_requirements,
        List<String> unsupported_claims,
        boolean parse_failed,
        String raw_response
) {
    public record DimensionScore(int score, String reason) {
    }

    public static JudgeEvaluationResult parseFailed(String rawResponse) {
        DimensionScore zero = new DimensionScore(0, "judge response parse failed");
        return new JudgeEvaluationResult(
                zero, zero, zero, zero,
                "uncertain",
                List.of(),
                List.of(),
                true,
                rawResponse
        );
    }

    public JudgeEvaluationResult normalized() {
        return new JudgeEvaluationResult(
                normalize(factuality),
                normalize(tool_use),
                normalize(actionability),
                normalize(safety),
                normalizeVerdict(verdict),
                missing_requirements == null ? List.of() : missing_requirements,
                unsupported_claims == null ? List.of() : unsupported_claims,
                parse_failed,
                raw_response
        );
    }

    public double overallScore() {
        return (factuality.score() + tool_use.score() + actionability.score() + safety.score()) / 4.0;
    }

    private DimensionScore normalize(DimensionScore score) {
        if (score == null) {
            return new DimensionScore(0, "missing score");
        }
        int clamped = Math.max(0, Math.min(10, score.score()));
        return new DimensionScore(clamped, score.reason() == null ? "" : score.reason());
    }

    private String normalizeVerdict(String verdict) {
        if ("pass".equalsIgnoreCase(verdict)) return "pass";
        if ("fail".equalsIgnoreCase(verdict)) return "fail";
        return "uncertain";
    }
}
