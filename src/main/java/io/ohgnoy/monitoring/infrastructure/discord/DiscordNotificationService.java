package io.ohgnoy.monitoring.infrastructure.discord;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.playbook.ActionRecommendation;
import io.ohgnoy.monitoring.infrastructure.prometheus.VerificationResult;

import io.ohgnoy.monitoring.infrastructure.command.TemplateResolver;
import io.ohgnoy.monitoring.infrastructure.command.CommandResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.Map;

@Service
public class DiscordNotificationService {

    private static final Logger log = LoggerFactory.getLogger(DiscordNotificationService.class);

    private final RestClient restClient;
    private final String webhookUrl;
    private final PendingApprovalStore pendingApprovalStore;

    private final String botChannelId;
    private final ConversationSessionStore conversationSessionStore;

    public DiscordNotificationService(RestClient.Builder builder,
                                      @Value("${discord.webhook.url}") String webhookUrl,
                                      @Value("${discord.bot.channel-id:}") String botChannelId,
                                      PendingApprovalStore pendingApprovalStore,
                                      ConversationSessionStore conversationSessionStore) {
        this.restClient = builder.build();
        this.webhookUrl = webhookUrl;
        this.botChannelId = botChannelId;
        this.pendingApprovalStore = pendingApprovalStore;
        this.conversationSessionStore = conversationSessionStore;
    }

    public void sendAlert(AlertEvent alert,
                          String agentAnalysis,
                          VerificationResult verification,
                          ActionRecommendation recommendation) {

        String verificationLine = verification != null
                ? "🔍 **검증**: " + verification.toPromptLine()
                : "🔍 **검증**: -";

        String actionLine = buildActionLine(recommendation, alert);

        String content = """
                🔔 **Monitoring Alert**
                • Level: `%s`  |  Alert: `%s`
                • %s
                • Time: `%s`  |  ID: `%s`

                %s

                🤖 **Agent Analysis**
                %s
                """.formatted(
                alert.getLevel(),
                alert.getAlertName() != null ? alert.getAlertName() : alert.getMessage(),
                verificationLine,
                alert.getCreatedAt(),
                alert.getId(),
                actionLine,
                agentAnalysis == null || agentAnalysis.isBlank()
                        ? "_분석 결과를 생성하지 못했습니다._"
                        : agentAnalysis
        );

        sendToDiscord(content);

        // NEEDS_APPROVAL인 경우 승인 대기 저장
        if (recommendation != null
                && recommendation.category() == ActionRecommendation.Category.NEEDS_APPROVAL
                && recommendation.command() != null) {
            String resolvedCommand = resolveCommand(recommendation.command(), alert);
            if (resolvedCommand != null) {
                pendingApprovalStore.store(resolvedCommand, alert.getId(), botChannelId);
                log.info("승인 대기 저장: command='{}', alertId={}", resolvedCommand, alert.getId());
            }
        }

        // AUTO가 아닌 알림은 대화 세션 생성 (운영자가 후속 질문 가능하도록)
        if (!botChannelId.isBlank()
                && recommendation != null
                && recommendation.category() != ActionRecommendation.Category.AUTO) {
            conversationSessionStore.getOrCreate(botChannelId, alert.getId());
            log.info("대화 세션 생성: channelId={}, alertId={}", botChannelId, alert.getId());
        }
    }

    public void sendAutoExecuted(AlertEvent alert,
                                 String agentAnalysis,
                                 VerificationResult verification,
                                 ActionRecommendation recommendation,
                                 String executedCommand,
                                 CommandResult result) {
        String verificationLine = verification != null
                ? "🔍 **검증**: " + verification.toPromptLine()
                : "🔍 **검증**: -";

        String statusLine = result.isSuccess()
                ? "✅ **자동 실행 완료**"
                : "❌ **자동 실행 실패** (exit " + result.exitCode() + ")";
        String statusOutput = (result.isSuccess() ? result.output() : result.errorOutput());

        String content = """
                🔔 **Monitoring Alert** — AUTO 처리
                • Level: `%s`  |  Alert: `%s`
                • %s
                • Time: `%s`  |  ID: `%s`

                🤖 **Agent Analysis**
                %s

                %s: `%s`
                ```
                %s
                ```
                """.formatted(
                alert.getLevel(),
                alert.getAlertName() != null ? alert.getAlertName() : alert.getMessage(),
                verificationLine,
                alert.getCreatedAt(),
                alert.getId(),
                agentAnalysis == null || agentAnalysis.isBlank()
                        ? "_분석 결과를 생성하지 못했습니다._"
                        : agentAnalysis,
                statusLine,
                executedCommand,
                statusOutput == null ? "" : statusOutput.trim());

        sendToDiscord(content);
    }

    private String buildActionLine(ActionRecommendation rec, AlertEvent alert) {
        if (rec == null) return "";
        String command = resolveCommand(rec.command(), alert);
        return switch (rec.category()) {
            case AUTO ->
                    "✅ **자동 조치**: " + rec.description()
                    + (command != null ? "\n```" + command + "```" : "");
            case NEEDS_APPROVAL ->
                    "⚠️ **승인 필요**: " + rec.description()
                    + (command != null ? "\n```" + command + "```" : "")
                    + (command != null ? "\n> 허가하려면 Discord에 **`approve " + command + "`** 를 입력하세요." : "");
            case READ_ONLY ->
                    "📊 **정보 수집**: " + rec.description();
            case NONE ->
                    "🔧 **수동 조치 필요**: " + rec.description();
        };
    }

    private String resolveCommand(String command, AlertEvent alert) {
        return TemplateResolver.resolve(command, alert.getLabelsJson());
    }

    private void sendToDiscord(String content) {
        // Discord 메시지 최대 2000자 제한
        if (content.length() > 2000) {
            content = content.substring(0, 1990) + "\n...(생략)";
        }
        try {
            restClient.post()
                    .uri(webhookUrl)
                    .body(Map.of("content", content))
                    .retrieve()
                    .toBodilessEntity();
        } catch (Exception e) {
            log.error("Discord 전송 실패: {}", e.getMessage());
        }
    }
}
