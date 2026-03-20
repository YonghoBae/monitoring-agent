package io.ohgnoy.monitoring.agent.config;

import io.ohgnoy.monitoring.agent.service.DiscordBotListener;
import net.dv8tion.jda.api.JDA;
import net.dv8tion.jda.api.JDABuilder;
import net.dv8tion.jda.api.requests.GatewayIntent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConditionalOnProperty(name = "discord.bot.token")
public class DiscordBotConfig {

    private static final Logger log = LoggerFactory.getLogger(DiscordBotConfig.class);

    @Bean
    public JDA jda(DiscordBotListener listener,
                   @Value("${discord.bot.token}") String token) throws Exception {
        log.info("Discord Bot 초기화 중...");
        JDA jda = JDABuilder.createDefault(token)
                .enableIntents(GatewayIntent.GUILD_MESSAGES, GatewayIntent.MESSAGE_CONTENT)
                .addEventListeners(listener)
                .build()
                .awaitReady();
        log.info("Discord Bot 준비 완료: {}", jda.getSelfUser().getName());
        return jda;
    }
}
