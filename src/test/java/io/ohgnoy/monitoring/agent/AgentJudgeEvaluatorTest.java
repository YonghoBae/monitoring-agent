package io.ohgnoy.monitoring.agent;

import io.ohgnoy.monitoring.agent.domain.AgentEvaluation;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.repository.AgentEvaluationRepository;
import io.ohgnoy.monitoring.agent.service.agent.AgentResult;
import io.ohgnoy.monitoring.agent.service.evaluation.AgentJudgeEvaluator;
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
        evaluator = new AgentJudgeEvaluator(emptyProvider, evaluationRepository, true);
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
    @DisplayName("parseScores가 정상 형식의 judge 응답을 파싱한다")
    void parseScores_normalFormat() {
        String judgeResponse = """
                Factuality: 8/10
                Prometheus 데이터로 CPU 급등을 확인했다.

                Tool Use: 7/10
                search_rag와 query_prometheus를 적절히 사용했다.

                Actionability: 9/10
                상위 프로세스 확인과 같은 즉시 실행 가능한 조치가 명확하다.

                Hallucination Risk: 8/10
                모든 결론이 수집된 데이터로 뒷받침된다.
                """;

        int[] scores = evaluator.parseScores(judgeResponse);

        assertThat(scores[0]).isEqualTo(8); // factuality
        assertThat(scores[1]).isEqualTo(7); // toolUse
        assertThat(scores[2]).isEqualTo(9); // actionability
        assertThat(scores[3]).isEqualTo(8); // hallucinationRisk
    }

    @Test
    @DisplayName("parseScores가 대소문자를 구분하지 않고 파싱한다")
    void parseScores_caseInsensitive() {
        String judgeResponse = """
                FACTUALITY: 6/10
                데이터 근거가 부분적이다.

                tool use: 5/10
                도구 호출이 다소 과다했다.

                ACTIONABILITY: 7/10
                조치가 구체적이다.

                hallucination risk: 9/10
                과장 없음.
                """;

        int[] scores = evaluator.parseScores(judgeResponse);

        assertThat(scores[0]).isEqualTo(6);
        assertThat(scores[1]).isEqualTo(5);
        assertThat(scores[2]).isEqualTo(7);
        assertThat(scores[3]).isEqualTo(9);
    }

    @Test
    @DisplayName("parseScores가 점수 없는 응답에서 기본값 5를 반환한다")
    void parseScores_missingScore_returnsDefault() {
        String malformedResponse = "judge가 형식을 지키지 않았습니다.";

        int[] scores = evaluator.parseScores(malformedResponse);

        assertThat(scores[0]).isEqualTo(5);
        assertThat(scores[1]).isEqualTo(5);
        assertThat(scores[2]).isEqualTo(5);
        assertThat(scores[3]).isEqualTo(5);
    }

    @Test
    @DisplayName("점수가 1-10 범위를 벗어나면 clamp 처리된다")
    void parseScores_outOfRange_isClamped() {
        String judgeResponse = """
                Factuality: 0/10
                범위 밖 점수.

                Tool Use: 15/10
                범위 밖 점수.

                Actionability: 5/10
                정상.

                Hallucination Risk: 5/10
                정상.
                """;

        int[] scores = evaluator.parseScores(judgeResponse);

        assertThat(scores[0]).isEqualTo(1); // 0 → clamp to 1
        assertThat(scores[1]).isEqualTo(10); // 15 → clamp to 10
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
