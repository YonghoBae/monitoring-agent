package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.service.AlertVectorService;
import io.ohgnoy.monitoring.agent.service.AlertVerifier;
import io.ohgnoy.monitoring.agent.service.CommandExecutorService;
import io.ohgnoy.monitoring.agent.service.LokiQueryService;
import io.ohgnoy.monitoring.agent.service.PrometheusQueryService;
import org.springframework.stereotype.Component;

/**
 * ReAct 루프 실행마다 새 AgentTools 인스턴스를 생성한다.
 * AgentTools는 요청별 추론 로그(reasoningLog)를 내부에 누적하므로
 * 공유 빈으로 사용하면 안 된다.
 */
@Component
public class AgentToolsFactory {

    private final AlertVerifier alertVerifier;
    private final PrometheusQueryService prometheusQuery;
    private final LokiQueryService lokiQuery;
    private final AlertVectorService vectorService;
    private final CommandExecutorService commandExecutorService;

    public AgentToolsFactory(AlertVerifier alertVerifier,
                              PrometheusQueryService prometheusQuery,
                              LokiQueryService lokiQuery,
                              AlertVectorService vectorService,
                              CommandExecutorService commandExecutorService) {
        this.alertVerifier = alertVerifier;
        this.prometheusQuery = prometheusQuery;
        this.lokiQuery = lokiQuery;
        this.vectorService = vectorService;
        this.commandExecutorService = commandExecutorService;
    }

    /**
     * AgentTools 단독 인스턴스 반환 (추론 로그 접근용).
     * ReActAgent가 도구 호출 후 reasoningLog를 읽기 위해 참조를 유지해야 하므로
     * 매 ReAct 루프마다 새 인스턴스를 생성한다.
     */
    public AgentTools createAgentTools() {
        return new AgentTools(alertVerifier, prometheusQuery, lokiQuery, vectorService, commandExecutorService);
    }
}
