package io.ohgnoy.monitoring.agent.repository;

import io.ohgnoy.monitoring.agent.domain.ResolutionRecord;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface ResolutionRecordRepository extends JpaRepository<ResolutionRecord, Long> {

    Optional<ResolutionRecord> findByAlertEventId(Long alertEventId);
}
