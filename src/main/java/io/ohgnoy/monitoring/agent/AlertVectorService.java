package io.ohgnoy.monitoring.agent;

import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

@Service
public class AlertVectorService {

    private final VectorStore vectorStore;

    public AlertVectorService(VectorStore vectorStore) {
        this.vectorStore = vectorStore;
    }

    private static final String METADATA_LEVEL = "level";
    private static final String METADATA_CREATED_AT = "createdAt";

    /**
     * 알람 엔티티를 PgVector에 임베딩/인덱싱한다.
     */
    public void indexAlert(AlertEvent alert) {
        Document doc = new Document(
                String.valueOf(alert.getId()),              // id
                alert.getMessage(),                         // content
                Map.of(
                        METADATA_LEVEL, alert.getLevel(),
                        METADATA_CREATED_AT, alert.getCreatedAt().toString()
                )                                           // metadata
        );
        vectorStore.add(List.of(doc));
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
