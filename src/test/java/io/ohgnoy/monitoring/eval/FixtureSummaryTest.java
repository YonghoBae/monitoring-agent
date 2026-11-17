package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import static org.assertj.core.api.Assertions.assertThat;

class FixtureSummaryTest {
    @TempDir Path directory;
    @Test
    void unsupportedFixtureDoesNotProduceMisleadingModelRanking() throws Exception {
        var record = new ObjectMapper().createObjectNode().put("fixtureUnsupported", true);
        new LiveEvalRunner().writeSummary(directory, List.of(record), 1);
        String summary = Files.readString(directory.resolve("summary.md"));
        assertThat(summary).contains("미판정", "비교는 생성하지 않습니다").doesNotContain("pass rate", "Arm 비교");
    }
}
