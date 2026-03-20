package io.ohgnoy.monitoring.agent;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class MonitoringAgentApplication {

	public static void main(String[] args) {
		SpringApplication.run(MonitoringAgentApplication.class, args);
	}

}
