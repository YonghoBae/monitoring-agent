package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import java.nio.file.Files;
import java.nio.file.Path;
import static org.junit.jupiter.api.Assertions.*;

/** Published request-schema checks only; no world, tools, or model is started. */
class LegacyHarnessSchemaTest {
    static final ObjectMapper JSON = new ObjectMapper();

    @Test void actualProspectiveDatasetAcceptsAll81FieldsAndEightMeasurements() throws Exception {
        var dataset = JSON.readTree(Files.readString(Path.of("eval/v5/legacy-migration/dataset.json")));
        int fields = 0, measurements = 0;
        assertEquals(35, dataset.path("scenarios").size());
        for (var scene : dataset.path("scenarios")) for (var field : scene.path("answer_fields")) {
            assertDoesNotThrow(() -> LegacyHarnessComparisonRunner.validatePublishedField(field));
            fields++;
            if (field.has("measurement")) measurements++;
            ObjectNode originalDescriptor = field.deepCopy();
            originalDescriptor.remove("measurement");
            assertDoesNotThrow(() -> LegacyHarnessComparisonRunner.validatePublishedField(originalDescriptor));
        }
        assertEquals(81, fields); assertEquals(8, measurements);
    }

    @Test void metadataCannotAddGoldQueriesOrUndocumentedProperties() throws Exception {
        ObjectNode field = (ObjectNode) JSON.readTree("{\"key\":\"load\",\"question\":\"Report load\",\"type\":\"number\",\"unit\":\"%\"}");
        for (String name : new String[]{"gold", "expected_value", "query", "reference_event_offsets_seconds"}) {
            ObjectNode bad = field.deepCopy(); bad.put(name, "hidden");
            assertThrows(IllegalArgumentException.class, () -> LegacyHarnessComparisonRunner.validatePublishedField(bad), name);
            ObjectNode badMetadata = field.deepCopy();
            badMetadata.putObject("measurement").put("lookback_seconds", 300).put("aggregation", "rate").put(name, "hidden");
            assertThrows(IllegalArgumentException.class, () -> LegacyHarnessComparisonRunner.validatePublishedField(badMetadata), name);
        }
    }

    @Test void metadataRequiresPositiveIntegerLookbackAndDocumentedAggregation() throws Exception {
        ObjectNode field = (ObjectNode) JSON.readTree("{\"key\":\"events\",\"question\":\"Report events\",\"type\":\"number\",\"unit\":\"count\"}");
        for (String metadata : new String[]{"null", "[]", "{}",
                "{\"lookback_seconds\":300}", "{\"aggregation\":\"rate\"}",
                "{\"lookback_seconds\":true,\"aggregation\":\"rate\"}",
                "{\"lookback_seconds\":\"300\",\"aggregation\":\"rate\"}",
                "{\"lookback_seconds\":300.0,\"aggregation\":\"rate\"}",
                "{\"lookback_seconds\":0,\"aggregation\":\"rate\"}",
                "{\"lookback_seconds\":-1,\"aggregation\":\"rate\"}",
                "{\"lookback_seconds\":300,\"aggregation\":\"mean\"}"}) {
            ObjectNode bad = field.deepCopy(); bad.set("measurement", JSON.readTree(metadata));
            assertThrows(IllegalArgumentException.class, () -> LegacyHarnessComparisonRunner.validatePublishedField(bad), metadata);
        }
        for (String aggregation : new String[]{"rate", "increase"}) {
            ObjectNode valid = field.deepCopy();
            valid.putObject("measurement").put("lookback_seconds", 300).put("aggregation", aggregation);
            assertDoesNotThrow(() -> LegacyHarnessComparisonRunner.validatePublishedField(valid));
        }
    }
}
