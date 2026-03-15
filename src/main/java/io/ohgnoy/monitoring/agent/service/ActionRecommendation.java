package io.ohgnoy.monitoring.agent.service;

public record ActionRecommendation(
        String description,
        Category category,
        String command        // 실행 명령어 템플릿 (null이면 없음)
) {
    public enum Category {
        AUTO,            // 즉시 자동 실행 (가역적이고 안전한 작업)
        NEEDS_APPROVAL,  // 사용자 Discord 승인 후 실행
        READ_ONLY,       // 정보 수집만 (실행 X)
        NONE             // 자동 조치 없음
    }

    public String toPromptLine() {
        return switch (category) {
            case AUTO           -> "[자동 실행 가능] " + description;
            case NEEDS_APPROVAL -> "[승인 필요] " + description;
            case READ_ONLY      -> "[정보 수집] " + description;
            case NONE           -> "[수동 조치 필요] " + description;
        };
    }
}
