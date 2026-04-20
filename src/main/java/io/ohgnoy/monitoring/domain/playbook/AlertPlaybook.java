package io.ohgnoy.monitoring.domain.playbook;

import org.springframework.stereotype.Component;

import java.util.Map;

import static io.ohgnoy.monitoring.domain.playbook.ActionRecommendation.Category.*;

/**
 * alertName별 권장 조치 정의.
 * Gemini가 자유롭게 행동을 결정하지 않고, 미리 허가된 목록에서만 선택한다.
 */
@Component
public class AlertPlaybook {

    private static final Map<String, ActionRecommendation> PLAYBOOK = Map.ofEntries(
            // 컨테이너
            Map.entry("ContainerRestarting",
                    new ActionRecommendation("컨테이너 재시작", NEEDS_APPROVAL, "docker restart {name}")),
            Map.entry("ContainerOOMKilled",
                    new ActionRecommendation("컨테이너 재시작", NEEDS_APPROVAL, "docker restart {name}")),
            Map.entry("ContainerHighMemoryUsage",
                    new ActionRecommendation("메모리 사용 현황 수집", READ_ONLY, null)),
            Map.entry("ContainerDown",
                    new ActionRecommendation("컨테이너 재시작", NEEDS_APPROVAL, "docker restart {name}")),

            // 호스트
            Map.entry("HostHighCpuLoad",
                    new ActionRecommendation("CPU 점유 상위 프로세스 확인", READ_ONLY, null)),
            Map.entry("HostHighMemoryUsage",
                    new ActionRecommendation("메모리 점유 상위 프로세스 확인", READ_ONLY, null)),

            // GPU
            Map.entry("GPUHighTemperature",
                    new ActionRecommendation("GPU 부하 프로세스 확인", READ_ONLY, null)),
            Map.entry("GPUHighMemoryUsage",
                    new ActionRecommendation("GPU 메모리 점유 프로세스 확인", READ_ONLY, null)),
            Map.entry("GPUUtilizationStuckHigh",
                    new ActionRecommendation("GPU 작업 목록 확인", READ_ONLY, null)),
            Map.entry("GPUDcgmExporterDown",
                    new ActionRecommendation("dcgm-exporter 재시작", AUTO, "docker restart dcgm-exporter")),

            // Apollo
            Map.entry("ApolloGameHighFrameLatency",
                    new ActionRecommendation("Apollo 세션 상태 확인", READ_ONLY, null)),
            Map.entry("ApolloGameInputBacklog",
                    new ActionRecommendation("Apollo 세션 상태 확인", READ_ONLY, null)),
            Map.entry("ApolloGeneralTypingLag",
                    new ActionRecommendation("Apollo 세션 상태 확인", READ_ONLY, null))
    );

    public ActionRecommendation lookup(String alertName) {
        return PLAYBOOK.getOrDefault(alertName,
                new ActionRecommendation("정의된 조치 없음", NONE, null));
    }
}
