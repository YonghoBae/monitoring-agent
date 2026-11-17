# Supplemental legacy tool-boundary checks

All four requested semantic exposure checks passed with actual enhanced callbacks and isolated `NumericEvalWorld` fixtures. No model or paid API calls were made. No existing source, world, gold or prior preflight artifact was changed.

| Case | Actual delivered evidence | Supported boundary |
| --- | --- | --- |
| host_oom_killer | `query_loki(kernel)` returned `empty`; `read_container_logs(kernel)` returned `unavailable`; the OOM counter and Docker model-load log remained reachable | The host-source killed-process diagnostic was not exposed. A Docker log mentioning a model loader does not establish the kernel's victim. |
| inventory_unavailable | `get_containers` returned an `unavailable` envelope, not a successful empty list | The fixture's internal empty array cannot be interpreted as a counted empty running-container inventory. |
| docker_target_port_mismatch | Inspection exposed host 9010 mapped to `8081/tcp`; the separate startup log exposed listener 8080 | Both necessary observations are delivered and establish a mismatch. |
| docker_target_port_correct | Inspection exposed host 9010 mapped to `8080/tcp`; the separate startup log exposed listener 8080 | Both necessary observations are delivered and establish a match. |

The host case also queried the supplied knowledge-base tool, which returned empty. No delivered response contained the hidden killed-process diagnostic or its PID. The underlying factory dispatch for both log routes filters `source=docker`; host/kernel records are not returned just because they exist in the fixture's source JSON. The separate host/systemd-timesyncd log uses the same dispatch predicate; this is a source-code boundary observation, not a claim that a fifth case was executed.

Each case built the enhanced callback descriptors twice and compared their names, descriptions and schemas. The comparison runner uses this common enhanced factory for both compact and Pi paths. The checks captured exact `AgentExecution` output envelopes and verified their fixed observation timestamp, absence of private gold/family/phase metadata, and zero mutation events. This establishes the tested factory/callback contract, not a live model or Pi transport test.

[LegacySemanticBoundaryTest.java](../src/test/java/io/ohgnoy/monitoring/eval/LegacySemanticBoundaryTest.java) is a separate opt-in test:

```sh
rtk env RUN_LEGACY_SEMANTIC_BOUNDARY_TESTS=1 ./gradlew evalRun --tests io.ohgnoy.monitoring.eval.LegacySemanticBoundaryTest --offline
```

[semantic-boundary-preflight.json](../eval/v5/legacy-migration/semantic-boundary-preflight.json) records **4 passed, 0 failed, 0 errors, 0 skipped**, exact per-case artifact hashes, the copied JUnit identity, source/built/sidecar hashes and the preserved prior-gate hashes. The original execution artifacts remain under `build/eval/legacy-semantic-boundary-1794847521982`; byte-identical copies are under `eval/v5/legacy-migration/semantic-boundary-evidence-20261117`.

The earlier 35-case replay manifest and its evidence summary retain their original hashes. This supplement does not silently replace or expand that earlier test result. No running `monitoring-numeric-fixture` containers remained after completion. The source reviewer can now use these observed boundaries when deciding the separate all-field source-audit gate.
