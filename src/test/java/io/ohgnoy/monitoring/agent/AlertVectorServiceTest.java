package io.ohgnoy.monitoring.agent;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;

import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

class AlertVectorServiceTest {

    @Mock
    private VectorStore vectorStore;

    @InjectMocks
    private AlertVectorService alertVectorService;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    void indexAlert_convertsEventToDocument() {
        AlertEvent alert = new AlertEvent("ERROR", "database down");
        setId(alert, 99L);
        LocalDateTime createdAt = alert.getCreatedAt();

        alertVectorService.indexAlert(alert);

        ArgumentCaptor<List<Document>> captor = ArgumentCaptor.forClass(List.class);
        verify(vectorStore).add(captor.capture());
        List<Document> docs = captor.getValue();
        assertThat(docs).hasSize(1);
        Document doc = docs.get(0);
        assertThat(doc.getId()).isEqualTo("99");
        assertThat(doc.getText()).isEqualTo("database down");
        assertThat(doc.getMetadata()).containsEntry("level", "ERROR");
        assertThat(doc.getMetadata()).containsEntry("createdAt", createdAt.toString());
    }

    @Test
    void searchSimilar_delegatesToVectorStore() {
        when(vectorStore.similaritySearch(org.mockito.ArgumentMatchers.any(SearchRequest.class))).thenReturn(List.of());

        List<Document> documents = alertVectorService.searchSimilar("timeout", 2);

        assertThat(documents).isEmpty();
        ArgumentCaptor<SearchRequest> captor = ArgumentCaptor.forClass(SearchRequest.class);
        verify(vectorStore).similaritySearch(captor.capture());
        verifyNoMoreInteractions(vectorStore);

        SearchRequest request = captor.getValue();
        assertThat(request.getQuery()).isEqualTo("timeout");
        assertThat(request.getTopK()).isEqualTo(2);
    }

    private static void setId(AlertEvent alertEvent, Long id) {
        try {
            var idField = AlertEvent.class.getDeclaredField("id");
            idField.setAccessible(true);
            idField.set(alertEvent, id);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("id 필드를 설정할 수 없습니다.", e);
        }
    }
}
