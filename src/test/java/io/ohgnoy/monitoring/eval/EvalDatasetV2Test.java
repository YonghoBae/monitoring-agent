package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import io.ohgnoy.monitoring.domain.playbook.ActionRecommendation;
import io.ohgnoy.monitoring.infrastructure.prometheus.VerificationResult;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.InputStream;
import java.util.HashSet;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("라이브 평가 데이터셋 v2 스키마 검증")
class EvalDatasetV2Test {

    @Test
    @DisplayName("30개 이상의 시나리오가 live mock과 채점 기준을 모두 가진다")
    void dataset_hasScenariosWithMocksAndCriteria() throws Exception {
        JsonNode root = loadDataset();

        assertThat(root.get("version").asInt()).isEqualTo(2);
        assertThat(root.get("scenarios").size()).isGreaterThanOrEqualTo(30);
        assertThat(root.get("default_containers")).isNotEmpty();

        Set<String> ids = new HashSet<>();
        for (JsonNode scenario : root.get("scenarios")) {
            String id = scenario.get("id").asText();
            assertThat(ids.add(id)).as("duplicate id: " + id).isTrue();

            assertThat(scenario.at("/alert/name").asText()).as(id + " alert.name").isNotBlank();
            assertThat(scenario.at("/alert/severity").asText()).as(id + " severity").isIn("warning", "critical");
            assertThat(scenario.get("situation").asText()).as(id + " situation").isNotBlank();

            // playbook은 유효한 Category여야 한다
            String category = scenario.at("/playbook/category").asText();
            assertThat(ActionRecommendation.Category.valueOf(category)).as(id + " playbook.category").isNotNull();

            // live 실행에 필요한 mock 필수 요소
            JsonNode mocks = scenario.get("mocks");
            assertThat(mocks).as(id + " mocks").isNotNull();
            String verifyStatus = mocks.at("/verify/status").asText();
            assertThat(VerificationResult.Status.valueOf(verifyStatus)).as(id + " verify.status").isNotNull();
            assertThat(mocks.get("metrics")).as(id + " mocks.metrics").isNotNull();
            assertThat(mocks.get("prometheus")).as(id + " mocks.prometheus").isNotNull();
            assertThat(mocks.get("rag")).as(id + " mocks.rag").isNotNull();
            assertThat(mocks.get("loki")).as(id + " mocks.loki").isNotNull();

            JsonNode expected = scenario.get("expected");
            assertThat(expected.get("must_check")).as(id + " must_check").isNotEmpty();
            assertThat(expected.get("acceptable_actions")).as(id + " acceptable_actions").isNotEmpty();
            assertThat(expected.get("forbidden_actions")).as(id + " forbidden_actions").isNotEmpty();

            JsonNode scores = expected.get("minimum_scores");
            for (String dim : new String[]{"factuality", "tool_use", "actionability", "safety"}) {
                assertThat(scores.get(dim).asInt()).as(id + " min " + dim).isBetween(0, 10);
            }
        }
    }

    private JsonNode loadDataset() throws Exception {
        ObjectMapper mapper = new ObjectMapper(new YAMLFactory());
        InputStream resource = EvalDatasetV2Test.class.getResourceAsStream("/eval-dataset-v2.yml");
        assertThat(resource).isNotNull();
        return mapper.readTree(resource);
    }
}
