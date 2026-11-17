# V5 replay preflight evidence

The final model-free replay gate passed all eight v5 cases and the existing numeric fixture integration test: **9 passed, 0 failed, 0 skipped**. It verified that the actual enhanced tool callbacks can reach the required recorded evidence and that private benchmark metadata is excluded from the investigation prompt. No model or paid API calls were made for this gate.

The final dataset SHA256 is `2f10a21b02a617c12fe009671b6e0c2cf54b673b9fd09889869f553066905447`. [The machine-readable validation record](../eval/v5/preflight/replay-validation.json) includes implementation and input hashes, per-case outcomes, commands, original artifact locations and copied JUnit checksums. This report and its evidence copies were created after the comparison implementation was frozen; they do not change that implementation.

## Failures and corrections before comparison

Static inspection found that `read_container_logs` caps results at 30 lines, while the fixture selected matching lines in insertion order. In case-202, the permission-denied diagnostic was the 55th source line, outside the first 30. At initial inspection all offsets were -30 seconds, so selecting a shorter permitted time window would not expose it. This finding was established by inspecting the actual callback and fixture data; it was **not** an executed failing log assertion.

The first actual run failed all eight cases earlier, during `NumericEvalWorld` startup. The shared numeric fixture rejected the intentionally empty metrics list with `world.series must be a nonempty list`. Consequently, none of those eight failed tests reached the log assertions. The [initial failure JUnit XML](../eval/v5/preflight/replay-initial-failure.xml) preserves those results.

The dataset hash recorded immediately after that failed run was `bd3040ed4b25a49063f6e5ba6bd1b316a7a556336bfb5e8de238dfe1dc330d11`. The builder had already corrected the offsets from captured timestamps before this run; it would be incorrect to describe that hash as the original all-minus-30-seconds dataset. The historical dataset bytes are not archived in this preflight directory.

Three precomparison corrections addressed the observed problems:

- Log-only worlds explicitly set `world.allow_empty_series=true`. The fixture permits that intentional empty list and skips TSDB import. Accidental empty lists remain invalid; no metric evidence was invented.
- The builder derives offsets from captured Docker timestamps or subprocess capture times. Source line content remains intact.
- The Java fixture now matches Loki's selection and rendering rules: select the newest entries before limiting, then display the selected entries chronologically. Equal-time selection uses reverse original index. Rendering preserves each source prefix up to the production 300-character cap and appends `...` when truncated. Replay timestamps use the fixed observation clock and explicit UTC `HH:mm:ss` formatting.

The ordering correction is generic. It neither increases the production line cap nor selects lines based on the expected diagnosis. Successful backup evidence uses the recorded exit status and the separate restore row-count result; it does not depend on the dump-complete phrase deep inside a truncated stdout line. Gold answers were not changed to accommodate the gate.

## Final recorded checks

The test instantiates `NumericEvalWorld` separately for every case, including its isolated real Prometheus fixture, then invokes the actual enhanced `get_containers` and `read_container_logs` callbacks through `AgentExecution`. Log retrieval requests a 30-minute window and retains the existing 30-line cap.

| Case | Source lines | Delivered lines | Required evidence reached |
| --- | ---: | ---: | --- |
| case-201 | 2 | 2 | Yes |
| case-202 | 55 | 30 | Yes |
| case-203 | 1 | 1 | Yes |
| case-204 | 76 | 30 | Yes |
| case-205 | 3 | 3 | Yes |
| case-206 | 79 | 30 | Yes |
| case-207 | 2 | 2 | Yes |
| case-208 | 1 | 1 | Yes |

The eight-case test also checks that delivered lines correspond to captured source text under the documented truncation, the recorded primary evidence exactly equals the returned tool envelope, and no mutation events occur. Partial views retain the explicit missing-detail record and do not expose the withheld permission or version-mismatch cause.

Prompt checks reject the actual case ID, family, source URL, phase and source event IDs. Replacing private metadata fields with canary values leaves the prompt unchanged. These checks cover the prompt builder and the tested fixture views; they do not claim that all possible side channels have been eliminated.

The [passing replay JUnit XML](../eval/v5/preflight/replay-final-pass.xml) records eight passes. The [existing numeric integration test XML](../eval/v5/preflight/numeric-regression-pass.xml) records one pass, checking that actual arithmetic and logical-clock behavior still work. All three XML copies are byte-identical to their original build outputs. After execution, no running containers with the isolated `monitoring-numeric-fixture` prefix remained.

The final invocation was:

```sh
rtk env RUN_V5_REPLAY_TESTS=1 RUN_NUMERIC_FIXTURE_TESTS=1 ./gradlew evalRun --tests io.ohgnoy.monitoring.eval.V5ReplayContractTest test --tests io.ohgnoy.monitoring.eval.NumericEvalWorldTest --offline
```

JUnit timestamps are stored in UTC on November 16; the review date is November 17, 2026 in Asia/Seoul. The initial failed test run and the successful rerun remain separately identifiable rather than being merged into a single success count.

## Scope of readiness

This gate establishes that a tested, permitted tool path reaches the evidence needed for these eight captured cases. An evaluated agent may still choose an unhelpful tool, omit a query or misinterpret a result. The gate is not a model performance result, a live Pi transport test, semantic-judge validation or evidence of general home-server representativeness.

The replay review was performed by a separate AI process, not an independent human auditor. The final outcome supports proceeding with the frozen, scoped comparison; it does not establish a model ranking.
