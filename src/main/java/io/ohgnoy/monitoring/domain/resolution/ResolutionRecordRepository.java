package io.ohgnoy.monitoring.domain.resolution;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface ResolutionRecordRepository extends JpaRepository<ResolutionRecord, Long> {

    Optional<ResolutionRecord> findByAlertEventId(Long alertEventId);
}
