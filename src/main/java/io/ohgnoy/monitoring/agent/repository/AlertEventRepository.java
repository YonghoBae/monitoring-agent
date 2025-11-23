package io.ohgnoy.monitoring.agent.repository;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AlertEventRepository extends JpaRepository<AlertEvent, Long> {

    List<AlertEvent> findTop20ByResolvedFalseOrderByCreatedAtDesc();

}
