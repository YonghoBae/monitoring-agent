package io.ohgnoy.monitoring;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import io.ohgnoy.monitoring.application.agent.AgentResult;
import io.ohgnoy.monitoring.application.agent.evaluation.AgentEvaluationRepository;
import io.ohgnoy.monitoring.application.agent.evaluation.AgentJudgeEvaluator;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.ObjectProvider;

import java.io.InputStream;
import java.util.HashSet;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@DisplayName("합성 평가 데이터셋 v1")
class SyntheticEvalDatasetTest {

    @Test
    @DisplayName("핵심 10개 시나리오가 새 스키마의 필수 기준을 가진다")
    void dataset_hasTenCoreScenariosWithRequiredCriteria() throws Exception {
        JsonNode root = loadDataset();

        assertThat(root.get("version").asInt()).isEqualTo(1);
        assertThat(root.get("scenarios")).hasSize(10);

        Set<String> ids = new HashSet<>();
        for (JsonNode scenario : root.get("scenarios")) {
            assertThat(ids.add(scenario.get("id").asText())).as("duplicate id").isTrue();
            assertThat(scenario.at("/alert/name").asText()).isNotBlank();
            assertThat(scenario.at("/alert/severity").asText()).isIn("warning", "critical");
            assertThat(scenario.get("situation").asText()).isNotBlank();

            JsonNode expected = scenario.get("expected");
            assertThat(expected.get("must_check")).isNotEmpty();
            assertThat(expected.get("acceptable_actions")).isNotEmpty();
            assertThat(expected.get("forbidden_actions")).isNotEmpty();

            JsonNode scores = expected.get("minimum_scores");
            assertScore(scores, "factuality");
            assertScore(scores, "tool_use");
            assertScore(scores, "actionability");
            assertScore(scores, "safety");
        }
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("평가 프롬프트에 시나리오 정답 기준을 주입할 수 있다")
    void evaluatorPrompt_includesScenarioCriteria() {
        ObjectProvider<ChatClient> emptyProvider = mock(ObjectProvider.class);
        AgentEvaluationRepository repository = mock(AgentEvaluationRepository.class);
        when(emptyProvider.getIfAvailable()).thenReturn(null);
        AgentJudgeEvaluator evaluator = new AgentJudgeEvaluator(
                emptyProvider,
                repository,
                new ObjectMapper(),
                true,
                1.0
        );

        AlertEvent alert = new AlertEvent("WARNING", "CPU load high");
        AgentResult result = new AgentResult("CPU pressure is sustained", "[query_prometheus] cpu=90", 1, null);
        String prompt = evaluator.buildEvaluationPrompt(alert, result, "must_check: verify alert and query CPU trend");

        assertThat(prompt).contains("[시나리오 정답 기준]");
        assertThat(prompt).contains("must_check: verify alert and query CPU trend");
    }

    private JsonNode loadDataset() throws Exception {
        ObjectMapper mapper = new ObjectMapper(new YAMLFactory());
        InputStream resource = SyntheticEvalDatasetTest.class.getResourceAsStream("/eval-dataset-v1.yml");
        assertThat(resource).isNotNull();
        return mapper.readTree(resource);
    }

    private void assertScore(JsonNode scores, String field) {
        assertThat(scores.get(field).asInt())
                .as(field)
                .isBetween(0, 10);
    }
}
