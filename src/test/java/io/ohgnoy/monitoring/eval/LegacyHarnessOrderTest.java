package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import org.junit.jupiter.api.Test;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Pure order checks on the actual 35 source test scenes; no fixture or model starts. */
class LegacyHarnessOrderTest {
    static final ObjectMapper JSON = new ObjectMapper();
    ArrayNode scenes() throws Exception {
        var result = JSON.createArrayNode();
        for (var scene : JSON.readTree(Files.readString(Path.of("eval/v4/dataset.json"))).path("scenarios"))
            if (scene.path("split").asText().equals("test")) result.add(scene);
        assertEquals(35, result.size()); return result;
    }

    @Test void actualGridHasOptimalGlobalRepeatAndFamilyBalance() throws Exception {
        var scenes = scenes(); var plan = LegacyHarnessComparisonRunner.orderPlan(scenes);
        var global = new int[2]; var repeatCounts = new int[3][2];
        var familyCounts = new HashMap<String,int[]>(); var cells = new HashSet<String>();
        for (var scene : scenes) for (int rep = 0; rep < 3; rep++) {
            var arms = LegacyHarnessComparisonRunner.orderedArms(plan, scene, rep);
            assertEquals(Set.copyOf(LegacyHarnessComparisonRunner.ARMS), Set.copyOf(arms));
            int first = arms.get(0).equals("pi_plus") ? 0 : 1;
            global[first]++; repeatCounts[rep][first]++;
            familyCounts.computeIfAbsent(scene.path("family").asText(), ignored -> new int[2])[first]++;
            for (String arm : arms) assertTrue(cells.add(scene.path("id").asText()+":"+rep+":"+arm));
        }
        assertEquals(210, cells.size()); assertArrayEquals(new int[]{53, 52}, global);
        assertArrayEquals(new int[]{18, 17}, repeatCounts[0]);
        assertArrayEquals(new int[]{17, 18}, repeatCounts[1]);
        assertArrayEquals(new int[]{18, 17}, repeatCounts[2]);
        for (var family : plan.sizes().entrySet()) {
            int[] counts = familyCounts.get(family.getKey());
            assertEquals(family.getValue() % 2, Math.abs(counts[0]-counts[1]), family.getKey());
        }
    }

    @Test void oddFamilyPhasesAlternateAndOrderIsRepeatable() throws Exception {
        var scenes = scenes(); var first = LegacyHarnessComparisonRunner.orderPlan(scenes);
        var second = LegacyHarnessComparisonRunner.orderPlan(scenes); int oddIndex = 0;
        assertEquals(first, second);
        for (var family : first.sizes().entrySet())
            assertEquals(family.getValue() % 2 == 0 ? 0 : oddIndex++ % 2, first.phases().get(family.getKey()));
        for (var scene : scenes) for (int rep = 0; rep < 3; rep++)
            assertEquals(LegacyHarnessComparisonRunner.orderedArms(first, scene, rep), LegacyHarnessComparisonRunner.orderedArms(second, scene, rep));
    }

    @Test void zeroPhaseForEveryFamilyWouldBeUnbalanced() throws Exception {
        var scenes = scenes(); var plan = LegacyHarnessComparisonRunner.orderPlan(scenes); int naivePiFirst = 0;
        for (var scene : scenes) for (int rep = 0; rep < 3; rep++)
            if ((plan.ordinals().get(scene.path("id").asText())+rep) % 2 == 0) naivePiFirst++;
        assertEquals(63, naivePiFirst); assertNotEquals(53, naivePiFirst);
    }

    @Test void duplicateCasesAndInvalidRepeatsAreRejected() throws Exception {
        var scenes = scenes(); var duplicate = JSON.createArrayNode().add(scenes.get(0)).add(scenes.get(0));
        assertThrows(IllegalArgumentException.class, () -> LegacyHarnessComparisonRunner.orderPlan(duplicate));
        var plan = LegacyHarnessComparisonRunner.orderPlan(scenes);
        assertThrows(IllegalArgumentException.class, () -> LegacyHarnessComparisonRunner.orderedArms(plan, scenes.get(0), 3));
    }
}
