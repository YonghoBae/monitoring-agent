package io.ohgnoy.monitoring.agent.repository;

import io.ohgnoy.monitoring.agent.domain.AgentEvaluation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;
import java.util.OptionalDouble;

public interface AgentEvaluationRepository extends JpaRepository<AgentEvaluation, Long> {

    List<AgentEvaluation> findTop20ByOrderByEvaluatedAtDesc();

    List<AgentEvaluation> findByAlertEventId(Long alertEventId);

    @Query("SELECT AVG(e.overallScore) FROM AgentEvaluation e")
    Double findAverageOverallScore();

    @Query("SELECT AVG(e.toolCallCount) FROM AgentEvaluation e")
    Double findAverageToolCallCount();
}
