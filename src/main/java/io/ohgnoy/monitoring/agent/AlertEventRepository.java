package io.ohgnoy.monitoring.agent;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AlertEventRepository extends JpaRepository<AlertEvent, Long> {

    List<AlertEvent> findTop20ByResolvedFalseOrderByCreatedAtDesc();

}
