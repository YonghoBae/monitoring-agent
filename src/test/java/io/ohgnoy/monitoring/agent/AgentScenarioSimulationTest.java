package io.ohgnoy.monitoring.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.agent.domain.AgentEvaluation;
import io.ohgnoy.monitoring.agent.repository.AgentEvaluationRepository;
import io.ohgnoy.monitoring.agent.service.ActionRecommendation;
import io.ohgnoy.monitoring.agent.service.ActionRecommendation.Category;
import io.ohgnoy.monitoring.agent.service.AlertVectorService;
import io.ohgnoy.monitoring.agent.service.AlertVerifier;
import io.ohgnoy.monitoring.agent.service.CommandExecutorService;
import io.ohgnoy.monitoring.agent.service.LokiQueryService;
import io.ohgnoy.monitoring.agent.service.PrometheusQueryService;
import io.ohgnoy.monitoring.agent.service.VerificationResult;
import io.ohgnoy.monitoring.agent.service.agent.AgentResult;
import io.ohgnoy.monitoring.agent.service.agent.AgentTools;
import io.ohgnoy.monitoring.agent.service.evaluation.AgentJudgeEvaluator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.mockito.stubbing.OngoingStubbing;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.ObjectProvider;

import java.io.InputStream;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static io.ohgnoy.monitoring.agent.service.ActionRecommendation.Category.NEEDS_APPROVAL;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.when;

/**
 * 에이전트 시나리오 시뮬레이션 테스트.
 *
 * 시나리오 정의(알람, Mock 응답, 도구 호출 순서, 기대 기준)는 eval-scenarios.json에서 관리한다.
 * 새 시나리오 추가 시 JSON만 수정하면 되고, 이 테스트 코드는 수정하지 않아도 된다.
 *
 * AgentTools 도구 메서드는 실제 코드가 실행된다 (reasoningLog, callCount 포함).
 * 외부 서비스(Prometheus, Loki, VectorStore) 응답은 JSON의 mocks 섹션으로 구성.
 * LLM 추론(어떤 도구를 어떤 순서로 호출할지)은 JSON의 simulation.toolCalls로 스크립트화.
 * Judge 평가 점수 파싱과 AgentEvaluation 생성은 실제 평가 로직이 실행된다.
 */
@DisplayName("에이전트 시나리오 시뮬레이션")
class AgentScenarioSimulationTest {

    @Mock AlertVerifier alertVerifier;
    @Mock PrometheusQueryService prometheusQuery;
    @Mock LokiQueryService lokiQuery;
    @Mock AlertVectorService vectorService;
    @Mock CommandExecutorService commandExecutorService;
    @Mock AgentEvaluationRepository evaluationRepository;

    private AgentJudgeEvaluator evaluator;

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        // chatClient=null → Judge LLM 없이 parseScores()만 실행, evaluationEnabled=true로 enabled 체크는 통과
        ObjectProvider<ChatClient> emptyProvider = org.mockito.Mockito.mock(ObjectProvider.class);
        when(emptyProvider.getIfAvailable()).thenReturn(null);
        evaluator = new AgentJudgeEvaluator(emptyProvider, evaluationRepository, true);
    }

    // ──────────────────────────────────────────────────────────────────────
    // 시나리오 로더 — eval-scenarios.json을 읽어 파라미터화 테스트 입력을 생성한다
    // ──────────────────────────────────────────────────────────────────────

    static Stream<Arguments> loadScenarios() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        InputStream resource = AgentScenarioSimulationTest.class
                .getResourceAsStream("/eval-scenarios.json");
        JsonNode root = mapper.readTree(resource);

        List<Arguments> args = new ArrayList<>();
        for (JsonNode scenario : root.get("scenarios")) {
            String displayName = scenario.get("id").asText()
                    + ": " + scenario.get("description").asText();
            args.add(Arguments.of(displayName, scenario));
        }
        return args.stream();
    }

    // ──────────────────────────────────────────────────────────────────────
    // 제네릭 시나리오 실행기
    // ──────────────────────────────────────────────────────────────────────

    @ParameterizedTest(name = "{0}")
    @MethodSource("loadScenarios")
    void runScenario(String name, JsonNode scenario) {
        // 1. Mock 구성
        setupMocks(scenario.get("mocks"));

        // 2. 도구 호출 시뮬레이션
        AgentTools tools = new AgentTools(alertVerifier, prometheusQuery, lokiQuery, vectorService, commandExecutorService);
        executeToolCalls(tools, scenario.get("simulation").get("toolCalls"));

        // 3. AgentResult 생성
        JsonNode sim = scenario.get("simulation");
        ActionRecommendation rec = parseRecommendation(sim.get("recommendation"));
        AgentResult result = new AgentResult(
                sim.get("conclusion").asText(),
                tools.getReasoningLog(),
                tools.getCallCount(),
                sim.get("reflectionResult").asText()
        );

        // 4. Judge 점수 파싱 및 AgentEvaluation 생성
        String judgeResponse = sim.get("judgeResponse").asText();
        int[] scores = evaluator.parseScores(judgeResponse);
        AgentEvaluation eval = new AgentEvaluation(
                0L,
                scenario.get("alert").get("alertName").asText(),
                result.conclusion(),
                result.iterationCount(),
                scores[0], scores[1], scores[2], scores[3],
                judgeResponse
        );

        // 5. expectedCriteria 검증
        assertCriteria(scenario.get("expectedCriteria"), result, eval, rec);

        printResult(name, result, eval, rec);
    }

    // ──────────────────────────────────────────────────────────────────────
    // Mock 구성 헬퍼
    // ──────────────────────────────────────────────────────────────────────

    private void setupMocks(JsonNode mocks) {
        setupRagMock(mocks.get("ragResults"));
        setupVerifyAlertMock(mocks.get("verifyAlert"));
        setupPrometheusMocks(mocks.get("prometheusResponses"));
        setupLokiMock(mocks.get("lokiResponse"));
    }

    private void setupRagMock(JsonNode ragResults) {
        List<Document> docs = new ArrayList<>();
        if (ragResults != null && ragResults.isArray()) {
            for (JsonNode r : ragResults) {
                docs.add(new Document(
                        r.get("text").asText(),
                        Map.of("type", r.get("type").asText(),
                               "outcome", r.get("outcome").asText())
                ));
            }
        }
        when(vectorService.searchSimilar(any(), eq(5))).thenReturn(docs);
    }

    private void setupVerifyAlertMock(JsonNode verifyAlert) {
        if (verifyAlert == null || verifyAlert.isNull()) return;
        String alertName = verifyAlert.get("alertName").asText();
        VerificationResult result = VerificationResult.confirmed(
                verifyAlert.get("value").asText(),
                verifyAlert.get("timestamp").asText()
        );
        when(alertVerifier.verify(eq(alertName), any())).thenReturn(result);
    }

    private void setupPrometheusMocks(JsonNode prometheusResponses) {
        if (prometheusResponses == null || prometheusResponses.isNull()) return;
        for (JsonNode pm : prometheusResponses) {
            String keyword = pm.get("keyword").asText();
            JsonNode responses = pm.get("responses");

            OngoingStubbing<String> stub = when(
                    prometheusQuery.querySummary(any(), contains(keyword), any(Instant.class), any(Instant.class))
            ).thenReturn(responses.get(0).asText());

            for (int i = 1; i < responses.size(); i++) {
                stub = stub.thenReturn(responses.get(i).asText());
            }
        }
    }

    private void setupLokiMock(JsonNode lokiResponse) {
        if (lokiResponse == null || lokiResponse.isNull()) return;
        String keyword = lokiResponse.get("keyword").asText();
        List<String> lines = new ArrayList<>();
        for (JsonNode line : lokiResponse.get("lines")) {
            lines.add(line.asText());
        }
        when(lokiQuery.queryRecentLogs(contains(keyword), any(Instant.class), any(Instant.class), anyInt()))
                .thenReturn(lines);
    }

    // ──────────────────────────────────────────────────────────────────────
    // 도구 호출 시뮬레이션 헬퍼
    // ──────────────────────────────────────────────────────────────────────

    private void executeToolCalls(AgentTools tools, JsonNode toolCalls) {
        for (JsonNode tc : toolCalls) {
            switch (tc.get("tool").asText()) {
                case "search_rag"       -> tools.search_rag(tc.get("query").asText());
                case "verify_alert"     -> tools.verify_alert(tc.get("alertName").asText(), tc.get("labelsJson").asText());
                case "query_prometheus" -> tools.query_prometheus(tc.get("promql").asText(), tc.get("timeRange").asText());
                case "query_loki"       -> tools.query_loki(tc.get("container").asText(), tc.get("timeRange").asText());
            }
        }
    }

    private ActionRecommendation parseRecommendation(JsonNode rec) {
        Category category = Category.valueOf(rec.get("category").asText());
        String command = rec.get("command").isNull() ? null : rec.get("command").asText();
        return new ActionRecommendation(rec.get("description").asText(), category, command);
    }

    // ──────────────────────────────────────────────────────────────────────
    // expectedCriteria 검증 헬퍼
    // ──────────────────────────────────────────────────────────────────────

    private void assertCriteria(JsonNode criteria, AgentResult result, AgentEvaluation eval, ActionRecommendation rec) {
        assertThat(result.iterationCount())
                .as("maxToolCalls")
                .isLessThanOrEqualTo(criteria.get("maxToolCalls").asInt());

        assertThat(eval.getOverallScore())
                .as("minJudgeScore")
                .isGreaterThanOrEqualTo(criteria.get("minJudgeScore").asDouble());

        if (criteria.get("shouldUsePrometheus").asBoolean())
            assertThat(result.reasoningChain()).as("shouldUsePrometheus").contains("query_prometheus");

        if (criteria.get("shouldUseLoki").asBoolean())
            assertThat(result.reasoningChain()).as("shouldUseLoki").contains("query_loki");

        if (criteria.get("shouldRecommendRestartApproval").asBoolean())
            assertThat(rec.category()).as("shouldRecommendRestartApproval").isEqualTo(NEEDS_APPROVAL);

        if (criteria.get("shouldNotRecommendRestart").asBoolean())
            assertThat(rec.category()).as("shouldNotRecommendRestart").isNotEqualTo(NEEDS_APPROVAL);

        if (criteria.get("shouldSuggestMemoryInvestigation").asBoolean())
            assertThat(result.conclusion()).as("shouldSuggestMemoryInvestigation").containsIgnoringCase("메모리");

        if (criteria.get("shouldCheckSessionCount").asBoolean())
            assertThat(result.reasoningChain()).as("shouldCheckSessionCount").contains("sessions");
    }

    // ──────────────────────────────────────────────────────────────────────
    // 출력 헬퍼
    // ──────────────────────────────────────────────────────────────────────

    private void printResult(String name, AgentResult result, AgentEvaluation eval, ActionRecommendation rec) {
        System.out.println("\n" + "=".repeat(60));
        System.out.println("[ " + name + " ]");
        System.out.println("=".repeat(60));
        System.out.println("▶ 도구 호출 수: " + result.iterationCount());
        System.out.println("▶ Reflection: " + result.reflectionResult());
        System.out.println("▶ 권고 카테고리: " + rec.category());
        System.out.println("\n[추론 로그]");
        System.out.println(result.reasoningChain());
        System.out.println("[결론]");
        System.out.println(result.conclusion());
        System.out.printf("[Judge 점수] Factuality=%d, Tool Use=%d, Actionability=%d, Hallucination=%d → Overall=%.2f%n",
                eval.getFactualityScore(), eval.getToolUseScore(),
                eval.getActionabilityScore(), eval.getHallucinationRiskScore(),
                eval.getOverallScore());
        System.out.println("▶ isHighQuality: " + eval.isHighQuality());
    }
}
