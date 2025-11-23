package io.ohgnoy.monitoring.agent.controller;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.dto.AlertResponse;
import io.ohgnoy.monitoring.agent.dto.CreateAlertRequest;
import io.ohgnoy.monitoring.agent.service.AlertService;
import io.ohgnoy.monitoring.agent.service.AlertVectorService;
import org.springframework.ai.document.Document;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/alerts")
public class AlertController {

    private static final String DEFAULT_TOP_K_VALUE = "5";

    private final AlertService alertService;
    private final AlertVectorService alertVectorService;

    public AlertController(AlertService alertService,
                           AlertVectorService alertVectorService) {
        this.alertService = alertService;
        this.alertVectorService = alertVectorService;
    }

    // 1) 알람 생성 + 임베딩 인덱싱
    @PostMapping
    public AlertResponse createAlert(@RequestBody CreateAlertRequest request) {
        AlertEvent alert = alertService.createAlert(
                request.getLevel(),
                request.getMessage()
        );
        return new AlertResponse(alert);
    }

    // 2) 최근 미해결 알람
    @GetMapping("/open")
    public List<AlertResponse> getOpenAlerts() {
        return alertService.getRecentOpenAlerts()
                .stream()
                .map(AlertResponse::new)
                .toList();
    }

    // 3) 쿼리로 유사 알람 검색 (벡터 검색)
    @GetMapping("/similar")
    public List<Document> searchSimilar(@RequestParam String query,
                                        @RequestParam(defaultValue = DEFAULT_TOP_K_VALUE) int topK) {
        return alertVectorService.searchSimilar(query, topK);
    }
}
