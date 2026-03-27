package io.ohgnoy.monitoring.agent.service;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.domain.ResolutionRecord;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;
import java.util.stream.Stream;

@Service
public class AlertVectorService {

    private final VectorStore vectorStore;

    public AlertVectorService(VectorStore vectorStore) {
        this.vectorStore = vectorStore;
    }

    private static final String METADATA_ALERT_ID = "alertId";
    private static final String METADATA_LEVEL = "level";
    private static final String METADATA_CREATED_AT = "createdAt";
    private static final String METADATA_ALERT_NAME = "alertName";

    /**
     * 알람 엔티티를 PgVector에 임베딩/인덱싱한다.
     */
    public void indexAlert(AlertEvent alert) {
        String content = Stream.of(alert.getAlertName(), alert.getMessage(), alert.getAnnotationSummary())
                .filter(s -> s != null && !s.isBlank())
                .collect(Collectors.joining(" | "));
        if (content.isBlank()) {
            content = alert.getMessage();
        }

        Map<String, Object> metadata = new HashMap<>();
        metadata.put(METADATA_ALERT_ID, alert.getId().toString());
        metadata.put(METADATA_LEVEL, alert.getLevel());
        metadata.put(METADATA_CREATED_AT, alert.getCreatedAt().toString());
        if (alert.getAlertName() != null) {
            metadata.put(METADATA_ALERT_NAME, alert.getAlertName());
        }

        Document doc = new Document(
                UUID.randomUUID().toString(),
                content,
                metadata
        );
        vectorStore.add(List.of(doc));
    }

    /**
     * 해결 기록을 PgVector에 인덱싱한다.
     * search_rag 도구 호출 시 과거 해결 사례로 검색된다.
     */
    public String indexResolution(ResolutionRecord record) {
        String content = Stream.of(
                record.getAlertName(),
                record.getAlertSummary(),
                record.getResolutionSteps(),
                "outcome=" + record.getOutcome()
        ).filter(s -> s != null && !s.isBlank())
                .collect(Collectors.joining(" | "));

        Map<String, Object> metadata = new HashMap<>();
        metadata.put("type", "resolution");
        metadata.put(METADATA_ALERT_NAME, record.getAlertName());
        metadata.put("outcome", record.getOutcome());
        metadata.put("alertEventId", record.getAlertEventId().toString());
        metadata.put(METADATA_CREATED_AT, record.getCreatedAt().toString());

        String docId = UUID.randomUUID().toString();
        vectorStore.add(List.of(new Document(docId, content, metadata)));
        return docId;
    }

    /**
     * 자연어 쿼리로 유사한 알람들을 검색한다.
     */
    public List<Document> searchSimilar(String query, int topK) {
        SearchRequest request = SearchRequest.builder()
                .query(query)
                .topK(topK)
                .build();

        return vectorStore.similaritySearch(request);
    }
}
