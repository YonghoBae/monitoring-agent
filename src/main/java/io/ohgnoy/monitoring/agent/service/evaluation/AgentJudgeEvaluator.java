package io.ohgnoy.monitoring.agent.service.evaluation;

import io.ohgnoy.monitoring.agent.domain.AgentEvaluation;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.repository.AgentEvaluationRepository;
import io.ohgnoy.monitoring.agent.service.agent.AgentResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * LLM-as-a-Judge 평가 서비스.
 *
 * ReActAgent의 응답 품질을 Gemini로 채점한다.
 * G-Eval 방식(Chain-of-Thought + 루브릭 기반)으로 4개 차원을 평가한다.
 *
 * 평가 차원:
 *   1. Factuality  — 수집한 데이터로 결론이 뒷받침되는가
 *   2. Tool Use    — 적절한 도구를 적절한 횟수만큼 사용했는가
 *   3. Actionability — 권고 조치가 구체적이고 실행 가능한가
 *   4. Hallucination Risk — 확인되지 않은 주장이 없는가 (오탐 위험)
 *
 * PPL 직접 측정은 Gemini API가 logprob를 미제공하여 불가. 대신:
 *   - 토큰 사용량 비율(입력 대비 출력)을 장황성 지표로 추적
 *   - 위 4개 루브릭 점수로 응답 품질을 간접 측정
 */
@Service
public class AgentJudgeEvaluator {

    private static final Logger log = LoggerFactory.getLogger(AgentJudgeEvaluator.class);

    // 점수 파싱 패턴: "Factuality: 8/10" 또는 "Factuality : 8 / 10"
    private static final Pattern SCORE_PATTERN =
            Pattern.compile("(?i)(Factuality|Tool Use|Actionability|Hallucination Risk)\\s*:\\s*(\\d+)\\s*/\\s*10");

    private final ChatClient judgeClient;
    private final AgentEvaluationRepository evaluationRepository;
    private final boolean evaluationEnabled;

    public AgentJudgeEvaluator(
            ObjectProvider<ChatClient> chatClientProvider,
            AgentEvaluationRepository evaluationRepository,
            @Value("${agent.evaluation.enabled:false}") boolean evaluationEnabled) {
        this.judgeClient = chatClientProvider.getIfAvailable();
        this.evaluationRepository = evaluationRepository;
        this.evaluationEnabled = evaluationEnabled;
    }

    /**
     * 에이전트 응답을 평가하고 결과를 DB에 저장한다.
     * 평가는 분석 결과 반환과 무관하므로 비동기로 실행한다.
     * chatModel이 없으면 평가를 건너뛴다.
     */
    @Async
    public void evaluate(AlertEvent alert, AgentResult agentResult) {
        if (!evaluationEnabled) {
            log.debug("[Judge] 평가 건너뜀 — agent.evaluation.enabled=false");
            return;
        }
        if (judgeClient == null) {
            log.debug("[Judge] 평가 건너뜀 — chatModel 없음");
            return;
        }

        log.info("[Judge] 평가 시작 — alertId={}, toolCalls={}",
                alert.getId(), agentResult.iterationCount());

        try {
            String judgeResponse = judgeClient.prompt()
                    .system(buildJudgeSystemPrompt())
                    .user(buildEvaluationPrompt(alert, agentResult))
                    .call()
                    .content();

            AgentEvaluation evaluation = parseAndSave(alert, agentResult, judgeResponse);

            log.info("[Judge] 평가 완료 — alertId={}, overall={}/10",
                    alert.getId(), evaluation.getOverallScore());

        } catch (Exception e) {
            log.warn("[Judge] 평가 실패 — alertId={}: {}", alert.getId(), e.getMessage());
        }
    }

    private AgentEvaluation parseAndSave(AlertEvent alert, AgentResult agentResult, String judgeResponse) {
        int[] scores = parseScores(judgeResponse);

        AgentEvaluation evaluation = new AgentEvaluation(
                alert.getId(),
                alert.getAlertName(),
                agentResult.conclusion(),
                agentResult.iterationCount(),
                scores[0], // factuality
                scores[1], // toolUse
                scores[2], // actionability
                scores[3], // hallucinationRisk
                judgeResponse
        );

        return evaluationRepository.save(evaluation);
    }

    /**
     * judge 응답에서 4개 차원 점수를 파싱한다.
     * 파싱 실패 시 해당 차원은 5점(중간값)으로 처리한다.
     */
    public int[] parseScores(String response) {
        int factuality = 5, toolUse = 5, actionability = 5, hallucinationRisk = 5;

        Matcher matcher = SCORE_PATTERN.matcher(response);
        while (matcher.find()) {
            String dimension = matcher.group(1).toLowerCase();
            int score = Integer.parseInt(matcher.group(2));
            score = Math.max(1, Math.min(10, score)); // clamp 1-10

            switch (dimension) {
                case "factuality"        -> factuality = score;
                case "tool use"          -> toolUse = score;
                case "actionability"     -> actionability = score;
                case "hallucination risk"-> hallucinationRisk = score;
            }
        }

        return new int[]{factuality, toolUse, actionability, hallucinationRisk};
    }

    private String buildJudgeSystemPrompt() {
        return """
                너는 인프라 모니터링 AI 에이전트의 응답 품질을 평가하는 심사관이야.
                아래 4가지 기준으로 각각 1~10점을 매겨.

                평가 기준:

                1. Factuality (데이터 기반 충실도)
                   - 수집한 메트릭/로그/RAG 결과로 결론이 뒷받침되는가?
                   - 10점: 모든 주장에 데이터 근거 있음
                   -  1점: 데이터 없이 추측만 나열

                2. Tool Use (도구 사용 적절성)
                   - 필요한 도구를 빠뜨리지 않았는가?
                   - 불필요한 반복 호출이 없었는가?
                   - 10점: 최소한의 도구로 필요한 정보를 모두 수집
                   -  1점: 중요한 도구 누락 또는 과도한 반복 호출

                3. Actionability (조치 실행 가능성)
                   - 권고 조치가 구체적이고 즉시 실행 가능한가?
                   - 근본 원인을 다루는가?
                   - 10점: 구체적이고 효과적인 조치 2~3개
                   -  1점: "더 조사 필요" 같은 모호한 조치만 나열

                4. Hallucination Risk (오탐/환각 위험)
                   - 확인되지 않은 사실을 단정하지 않았는가?
                   - 실제 정상 상황을 문제로 과장하지 않았는가?
                   - 10점: 모든 주장이 데이터로 검증됨
                   -  1점: 확인되지 않은 주장 또는 오탐 가능성 높음

                출력 형식 (이 형식을 정확히 지켜):
                Factuality: X/10
                [이유 한 문장]

                Tool Use: X/10
                [이유 한 문장]

                Actionability: X/10
                [이유 한 문장]

                Hallucination Risk: X/10
                [이유 한 문장]

                절대로 위 형식 외의 내용을 추가하지 마.
                """;
    }

    private String buildEvaluationPrompt(AlertEvent alert, AgentResult agentResult) {
        String toolCallInfo = agentResult.reasoningChain() == null || agentResult.reasoningChain().isBlank()
                ? "도구 호출 없음 (직접 응답)"
                : agentResult.reasoningChain();

        return """
                [원본 알람]
                알람명: %s
                레벨: %s
                메시지: %s
                레이블: %s
                발생 시각: %s

                [에이전트 도구 호출 내역 (%d회)]
                %s

                [에이전트 최종 결론]
                %s

                위 내용을 4가지 기준으로 평가해.
                """.formatted(
                alert.getAlertName(),
                alert.getLevel(),
                alert.getMessage(),
                alert.getLabelsJson(),
                alert.getStartsAt(),
                agentResult.iterationCount(),
                toolCallInfo,
                agentResult.conclusion()
        );
    }
}
