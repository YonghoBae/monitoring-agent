package io.ohgnoy.monitoring;

import io.ohgnoy.monitoring.application.agent.evaluation.AgentEvaluation;
import io.ohgnoy.monitoring.application.agent.evaluation.JudgeEvaluationResult;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.application.agent.evaluation.AgentEvaluationRepository;
import io.ohgnoy.monitoring.application.agent.AgentResult;
import io.ohgnoy.monitoring.application.agent.evaluation.AgentJudgeEvaluator;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.ObjectProvider;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

@DisplayName("AgentJudgeEvaluator 단위 테스트")
class AgentJudgeEvaluatorTest {

    @Mock
    private AgentEvaluationRepository evaluationRepository;

    private AgentJudgeEvaluator evaluator;

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        // chatClient=null → 평가 건너뜀 경로로 단위 테스트, evaluationEnabled=true로 enabled 체크는 통과
        ObjectProvider<ChatClient> emptyProvider = mock(ObjectProvider.class);
        when(emptyProvider.getIfAvailable()).thenReturn(null);
        evaluator = new AgentJudgeEvaluator(emptyProvider, evaluationRepository, new ObjectMapper(), true, 1.0);
    }

    @Test
    @DisplayName("chatModel이 없으면 evaluate()가 DB 저장하지 않는다")
    void evaluate_whenChatModelNull_doesNotSave() {
        AlertEvent alert = new AlertEvent("WARNING", "CPU spike");
        AgentResult result = new AgentResult(
                "CPU 과부하로 인한 성능 저하",
                "[search_rag] 유사 사례 없음\n[query_prometheus] CPU 85%",
                2, null
        );

        evaluator.evaluate(alert, result);

        verifyNoInteractions(evaluationRepository);
    }

    @Test
    @DisplayName("parseJudgeResponse가 정상 JSON judge 응답을 파싱한다")
    void parseJudgeResponse_normalJson() {
        String judgeResponse = """
                {
                  "factuality": {"score": 8, "reason": "Prometheus 데이터로 CPU 급등을 확인했다."},
                  "tool_use": {"score": 7, "reason": "search_rag와 query_prometheus를 사용했다."},
                  "actionability": {"score": 9, "reason": "상위 프로세스 확인 조치가 명확하다."},
                  "safety": {"score": 8, "reason": "수집된 데이터로 뒷받침된다."},
                  "verdict": "pass",
                  "missing_requirements": [],
                  "unsupported_claims": [],
                  "parse_failed": false,
                  "raw_response": ""
                }
                """;

        JudgeEvaluationResult result = evaluator.parseJudgeResponse(judgeResponse);

        assertThat(result.factuality().score()).isEqualTo(8);
        assertThat(result.tool_use().score()).isEqualTo(7);
        assertThat(result.actionability().score()).isEqualTo(9);
        assertThat(result.safety().score()).isEqualTo(8);
        assertThat(result.verdict()).isEqualTo("pass");
        assertThat(result.parse_failed()).isFalse();
    }

    @Test
    @DisplayName("parseJudgeResponse가 누락 필드를 기본값으로 정규화한다")
    void parseJudgeResponse_missingFields_areNormalized() {
        String judgeResponse = """
                {
                  "factuality": {"score": 6, "reason": "부분 근거"},
                  "tool_use": {"score": 5, "reason": "도구 과다"},
                  "actionability": {"score": 7, "reason": "구체적"},
                  "safety": null,
                  "verdict": "other",
                  "parse_failed": false
                }
                """;

        JudgeEvaluationResult result = evaluator.parseJudgeResponse(judgeResponse);

        assertThat(result.factuality().score()).isEqualTo(6);
        assertThat(result.tool_use().score()).isEqualTo(5);
        assertThat(result.actionability().score()).isEqualTo(7);
        assertThat(result.safety().score()).isZero();
        assertThat(result.verdict()).isEqualTo("uncertain");
        assertThat(result.missing_requirements()).isEmpty();
        assertThat(result.unsupported_claims()).isEmpty();
    }

    @Test
    @DisplayName("parseJudgeResponse가 깨진 응답을 parse_failed로 저장한다")
    void parseJudgeResponse_malformed_returnsParseFailed() {
        String malformedResponse = "judge가 형식을 지키지 않았습니다.";

        JudgeEvaluationResult result = evaluator.parseJudgeResponse(malformedResponse);

        assertThat(result.parse_failed()).isTrue();
        assertThat(result.factuality().score()).isZero();
        assertThat(result.tool_use().score()).isZero();
        assertThat(result.actionability().score()).isZero();
        assertThat(result.safety().score()).isZero();
        assertThat(result.raw_response()).isEqualTo(malformedResponse);
    }

    @Test
    @DisplayName("점수가 1-10 범위를 벗어나면 clamp 처리된다")
    void parseJudgeResponse_outOfRange_isClamped() {
        String judgeResponse = """
                {
                  "factuality": {"score": -1, "reason": "범위 밖"},
                  "tool_use": {"score": 15, "reason": "범위 밖"},
                  "actionability": {"score": 5, "reason": "정상"},
                  "safety": {"score": 5, "reason": "정상"},
                  "verdict": "fail",
                  "missing_requirements": ["verify_alert"],
                  "unsupported_claims": ["원인 단정"],
                  "parse_failed": false,
                  "raw_response": ""
                }
                """;

        JudgeEvaluationResult result = evaluator.parseJudgeResponse(judgeResponse);

        assertThat(result.factuality().score()).isZero();
        assertThat(result.tool_use().score()).isEqualTo(10);
        assertThat(result.missing_requirements()).containsExactly("verify_alert");
        assertThat(result.unsupported_claims()).containsExactly("원인 단정");
    }

    @Test
    @DisplayName("AgentEvaluation.isHighQuality()는 평균 7점 이상일 때 true를 반환한다")
    void agentEvaluation_isHighQuality() {
        AgentEvaluation high = new AgentEvaluation(
                1L, "HostHighCpuLoad", "결론", 3,
                8, 7, 8, 7, "피드백"
        );
        AgentEvaluation low = new AgentEvaluation(
                2L, "ContainerDown", "결론", 5,
                5, 5, 5, 5, "피드백"
        );

        assertThat(high.isHighQuality()).isTrue();
        assertThat(low.isHighQuality()).isFalse();
        assertThat(high.getOverallScore()).isEqualTo(7.5);
        assertThat(low.getOverallScore()).isEqualTo(5.0);
    }
}
