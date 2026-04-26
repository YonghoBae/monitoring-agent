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
            // 컨테이너 - 재시작 필요
            Map.entry("ContainerRestarting",
                    new ActionRecommendation("컨테이너 재시작", NEEDS_APPROVAL, "docker restart {name}")),
            Map.entry("ContainerOOMKilled",
                    new ActionRecommendation("컨테이너 재시작", NEEDS_APPROVAL, "docker restart {name}")),
            Map.entry("ContainerDown",
                    new ActionRecommendation("컨테이너 재시작", NEEDS_APPROVAL, "docker restart {name}")),
            Map.entry("ContainerKilled",
                    new ActionRecommendation("컨테이너 재시작", NEEDS_APPROVAL, "docker restart {name}")),

            // 컨테이너 - 정보 수집
            Map.entry("ContainerHighMemoryUsage",
                    new ActionRecommendation("메모리 사용 현황 수집", READ_ONLY, null)),
            Map.entry("ContainerHighCpuUtilization",
                    new ActionRecommendation("CPU 점유 상위 컨테이너 확인", READ_ONLY, null)),
            Map.entry("ContainerHighThrottleRate",
                    new ActionRecommendation("컨테이너 CPU 스로틀 현황 확인", READ_ONLY, null)),
            Map.entry("ContainerVolumeUsage",
                    new ActionRecommendation("컨테이너 볼륨 inode 사용량 확인", READ_ONLY, null)),
            Map.entry("ContainerAbsent",
                    new ActionRecommendation("cAdvisor 컨테이너 메트릭 수집 상태 확인", READ_ONLY, null)),

            // 호스트 - CPU
            Map.entry("HostHighCpuLoad",
                    new ActionRecommendation("CPU 점유 상위 프로세스 확인", READ_ONLY, null)),
            Map.entry("HostCpuHighIowait",
                    new ActionRecommendation("I/O 부하 원인 프로세스/디스크 확인", READ_ONLY, null)),
            Map.entry("HostCpuPressureHigh",
                    new ActionRecommendation("CPU PSI 압력 분석", READ_ONLY, null)),

            // 호스트 - 메모리
            Map.entry("HostHighMemoryUsage",
                    new ActionRecommendation("메모리 점유 상위 프로세스 확인", READ_ONLY, null)),
            Map.entry("HostOutOfMemory",
                    new ActionRecommendation("메모리 점유 컨테이너/프로세스 확인", READ_ONLY, null)),
            Map.entry("HostSwapIsFillingUp",
                    new ActionRecommendation("메모리 점유 프로세스 확인", READ_ONLY, null)),
            Map.entry("HostOomKillDetected",
                    new ActionRecommendation("OOM 킬 발생 프로세스 확인", READ_ONLY, null)),
            Map.entry("HostMemoryPressureHigh",
                    new ActionRecommendation("메모리 PSI 압력 분석", READ_ONLY, null)),
            Map.entry("HostMemoryPressureStalled",
                    new ActionRecommendation("메모리 완전 정지 - 긴급 메모리 확보 검토", READ_ONLY, null)),

            // 호스트 - 디스크
            Map.entry("HostOutOfDiskSpace",
                    new ActionRecommendation("대용량 파일/로그 탐색", READ_ONLY, null)),
            Map.entry("HostDiskMayFillIn24Hours",
                    new ActionRecommendation("디스크 증가 추세 분석", READ_ONLY, null)),
            Map.entry("HostOutOfInodes",
                    new ActionRecommendation("inode 소모 경로 탐색", READ_ONLY, null)),
            Map.entry("HostFilesystemDeviceError",
                    new ActionRecommendation("파일시스템 장치 오류 확인", READ_ONLY, null)),
            Map.entry("HostIoPressureHigh",
                    new ActionRecommendation("I/O PSI 압력 분석", READ_ONLY, null)),

            // 호스트 - 시스템
            Map.entry("HostSystemdServiceCrashed",
                    new ActionRecommendation("실패한 systemd 서비스 상태 및 로그 확인", READ_ONLY, null)),
            Map.entry("HostPhysicalComponentTooHot",
                    new ActionRecommendation("하드웨어 온도 확인", READ_ONLY, null)),
            Map.entry("HostNodeOvertemperatureAlarm",
                    new ActionRecommendation("온도 임계값 초과 컴포넌트 확인", READ_ONLY, null)),

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
