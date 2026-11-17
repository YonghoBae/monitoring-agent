package io.ohgnoy.monitoring.drill;

import io.ohgnoy.monitoring.application.alert.ResolutionFeedbackService;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.alert.AlertEventRepository;
import io.ohgnoy.monitoring.domain.resolution.ResolutionRecord;
import io.ohgnoy.monitoring.domain.resolution.ResolutionRecordRepository;
import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.ai.ollama.OllamaEmbeddingModel;
import org.springframework.ai.ollama.api.OllamaApi;
import org.springframework.ai.ollama.api.OllamaEmbeddingOptions;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.pgvector.PgVectorStore;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** Opt-in live test; creates durable, explicitly synthetic records. Never runs in `test`. */
@Tag("drill")
@DataJpaTest(properties = {
        "spring.datasource.url=${DRILL_DB_URL}",
        "spring.datasource.username=${DRILL_DB_USERNAME}",
        "spring.datasource.password=${DRILL_DB_PASSWORD}",
        "spring.datasource.driver-class-name=org.postgresql.Driver",
        "spring.jpa.hibernate.ddl-auto=validate",
        "spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.PostgreSQLDialect",
        "spring.jpa.show-sql=false",
        "spring.jpa.properties.hibernate.format_sql=false"
})
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Transactional(propagation = Propagation.NOT_SUPPORTED)
@Import({ResolutionFeedbackService.class, AlertVectorService.class, ResolutionStorageDrill.LiveVectors.class})
class ResolutionStorageDrill {
    @Autowired AlertEventRepository alerts;
    @Autowired ResolutionRecordRepository resolutions;
    @Autowired ResolutionFeedbackService feedback;
    @Autowired AlertVectorService vectors;
    @Autowired JdbcTemplate jdbc;

    @Test
    void verifiedRecoveryPersistsResolutionAndSearchableVector() {
        assertThat(System.getenv("DRILL_EXECUTE")).isEqualTo("verified-recovery");
        String id = required("DRILL_ID");
        String evidence = required("DRILL_EVIDENCE");
        assertThat(evidence).contains("healthy=1", "failed=0", "recovered=1", "synthetic=true");
        String labels = "{\"synthetic\":\"true\",\"source\":\"controlled-drill\",\"drillId\":\"" + id + "\"}";
        String summary = "[SYNTHETIC DRILL] Disposable HTTP container stopped, then restored; " + id;
        AlertEvent alert = new AlertEvent("INFO", summary, "SyntheticDrillHttpUnavailable", labels,
                summary, evidence, Instant.parse(required("DRILL_FAILURE_TIME")), "");
        alert.setVerificationStatus("CONFIRMED");
        alert.setReasoningChain("Observed blackbox probes on disposable fixture: healthy -> failed -> recovered. " + evidence);
        alert.resolve();
        alert = alerts.saveAndFlush(alert);

        String note = "[SYNTHETIC DRILL; operator=Codex harness; not autonomous LLM remediation] " + evidence;
        String response = feedback.recordOutcome(alert.getId(), "RESOLVED", note);
        assertThat(response).contains("피드백 기록 완료");
        AlertEvent stored = alerts.findById(alert.getId()).orElseThrow();
        assertThat(stored.isResolved()).isTrue();
        assertThat(stored.getResolutionRecordId()).isNotNull();
        ResolutionRecord record = resolutions.findById(stored.getResolutionRecordId()).orElseThrow();
        assertThat(record.getResolutionSteps()).isEqualTo(note);
        assertThat(record.getLabelsJson()).contains("synthetic", id);
        assertThat(record.getOutcome()).isEqualTo("RESOLVED");
        assertThat(record.getVectorDocId()).isNotBlank();
        Map<String, Object> vector = jdbc.queryForMap(
                "SELECT content, vector_dims(embedding) AS dims, metadata->>'type' AS type FROM vector_store WHERE id = ?::uuid",
                record.getVectorDocId());
        assertThat(vector.get("content").toString()).contains("SYNTHETIC DRILL", "recovered=1");
        assertThat(((Number) vector.get("dims")).intValue()).isEqualTo(384);
        assertThat(vector.get("type")).isEqualTo("resolution");
        assertThat(vectors.searchSimilar(summary, 5)).anyMatch(doc -> doc.getId().equals(record.getVectorDocId()));
        long beforeDuplicate = resolutions.count();
        assertThat(feedback.recordOutcome(alert.getId(), "RESOLVED", note)).contains("이미 피드백");
        assertThat(resolutions.count()).isEqualTo(beforeDuplicate);
        System.out.printf("DRILL_RESULT alertId=%d resolutionId=%d vectorId=%s synthetic=true retrieval=PASS duplicateGuard=PASS%n",
                alert.getId(), record.getId(), record.getVectorDocId());
    }

    private static String required(String name) {
        String value = System.getenv(name);
        assertThat(value).as(name).isNotBlank();
        return value;
    }

    @TestConfiguration
    static class LiveVectors {
        @Bean
        VectorStore vectorStore(JdbcTemplate jdbc) {
            OllamaEmbeddingModel embedding = OllamaEmbeddingModel.builder()
                    .ollamaApi(OllamaApi.builder().baseUrl(required("DRILL_OLLAMA_URL")).build())
                    .defaultOptions(OllamaEmbeddingOptions.builder().model("all-minilm").build())
                    .build();
            return PgVectorStore.builder(jdbc, embedding).dimensions(384).initializeSchema(false).build();
        }
    }
}
