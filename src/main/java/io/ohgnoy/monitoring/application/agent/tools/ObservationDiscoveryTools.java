package io.ohgnoy.monitoring.application.agent.tools;

import io.ohgnoy.monitoring.infrastructure.prometheus.PrometheusQueryService;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.loki.LokiQueryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.regex.Pattern;

/** Optional read-only discovery tools, enabled separately in comparative experiments. */
public class ObservationDiscoveryTools {
    private final PrometheusQueryService prometheus;
    private final CommandExecutorService containers;
    private final LokiQueryService logs;
    public ObservationDiscoveryTools(PrometheusQueryService prometheus){this(prometheus,null);}
    public ObservationDiscoveryTools(PrometheusQueryService prometheus,CommandExecutorService containers){this(prometheus,containers,null);}
    public ObservationDiscoveryTools(PrometheusQueryService prometheus,CommandExecutorService containers,LokiQueryService logs){this.prometheus=prometheus;this.containers=containers;this.logs=logs;}
    @Tool(description="Docker가 확인한 로그 파일 경로로 해당 컨테이너의 Loki 로그를 조회한다. 로그 본문에 컨테이너 이름이 없어도 되고, 중지된 컨테이너도 지원한다. 컨테이너 조사 시 이 도구를 우선 사용한다.")
    public String read_container_logs(@ToolParam(description="정확한 Docker 컨테이너 이름") String containerName,
                                      @ToolParam(description="조회 기간(분), 1~1440") int minutes) {
        if(minutes<1||minutes>1440)throw new IllegalArgumentException("Minutes must be between 1 and 1440");
        if(containers==null||logs==null)throw new IllegalStateException("Container log inspection unavailable");
        String path=containers.containerLogPath(containerName);
        try {
            String selector="{job=\"docker\",filename="+new ObjectMapper().writeValueAsString(path)+"}";
            Instant end=Instant.now();var lines=logs.queryRecentLogs(selector,end.minus(minutes,ChronoUnit.MINUTES),end,30);
            return lines.isEmpty()?"로그 없음: "+containerName:String.join("\n",lines);
        } catch(com.fasterxml.jackson.core.JsonProcessingException e){throw new IllegalStateException("Invalid log path",e);}
    }
    @Tool(description="정확한 컨테이너 이름으로 상태·이미지·종료코드·OOMKilled·재시작횟수·health·포트 설정을 읽는다. 중지된 컨테이너도 조사할 수 있다. 환경변수나 비밀은 반환하지 않는다.")
    public String inspect_container(@ToolParam(description="get_containers 또는 사용자 입력에서 확인한 컨테이너 이름") String containerName){
        if(containers==null)throw new IllegalStateException("Container inspection unavailable");
        return containers.inspectContainer(containerName);
    }
    @Tool(description="메트릭의 실제 레이블 이름·값과 최근 표본을 확인한다. 이름은 list_metrics로 찾고 레이블은 추측하지 않는다. 결과는 최근 5분 표본이며 현재 정상 여부나 단위를 보장하지 않는다.")
    public String describe_metric(@ToolParam(description="필터 없는 정확한 메트릭 이름") String metricName){
        if(metricName==null||!Pattern.matches("[a-zA-Z_:][a-zA-Z0-9_:]*",metricName))throw new IllegalArgumentException("정확한 메트릭 이름만 허용합니다");
        Instant now=Instant.now();String result=prometheus.querySummary(metricName,metricName,now.minus(5,ChronoUnit.MINUTES),now);
        return result==null?"최근 표본 없음. 존재하지 않음·수집 실패·기간 외 상태는 이 결과만으로 구분 불가.":result;
    }
}
