# Legacy replay tool-reachability preflight

**The scoped gate passed:** all 35 legacy test worlds opened successfully; all 34 numeric validation expressions produced a single delivered scalar within the existing gold tolerance at the fixed sample time; all 11 log-backed gold sources retained their 23 complete source lines. The sole numeric log witness was reachable in the intended window and absent from an excluding window. No model or paid API calls were made.

There were no scalar-ambiguity, precision, log-truncation or fixture-execution blockers in these checks. This does **not** certify all 62 categorical, numeric and unknown findings, agent discoverability or semantic answer correctness. Those require their separate source-coverage and scoring gates.

## What was exercised

[LegacyReplayContractTest.java](../src/test/java/io/ohgnoy/monitoring/eval/LegacyReplayContractTest.java) opens each of the 35 v4 test scenarios through the actual `NumericEvalWorld`, including its isolated real Prometheus fixture. It uses the actual enhanced callbacks through `AgentExecution`, with its fixed observation clock and exact returned envelope capture. Container and metric discovery execute in every world.

For each non-null `validation_expr`, the test calls `query_prometheus` with a 30-minute range. It reads the scalar printed after `현재=` in the **delivered** summary and checks the delivered sample timestamp. It compares that scalar with the existing gold value using the unchanged absolute tolerance. It does not use the raw Prometheus trace as a substitute for an omitted or rounded tool value, invent a metric, or choose a matching value from ambiguous multiple series.

All 34 expressions produced one identifiable current scalar. Four results had small nonzero differences, each within its declared tolerance:

| Case / field | Absolute scalar difference | Existing absolute tolerance |
| --- | ---: | ---: |
| container_throttled / throttle_percent | 0.000000000000025 | 0.1 |
| jellyfin_transcode_cpu / cpu_cores | 0.0000000000000123 | 0.01 |
| disk_io_saturation / busy_percent | 0.00000000000001 | 0.1 |
| question_disk_io_saturation / busy_percent | 0.00000000000001 | 0.1 |

These are differences in each validation expression's own scale, not an aggregate error statistic across units. This gate tests the requested expression's reachable value; it does not certify unit attribution in arbitrary model prose or establish that an agent will select the right expression.

Every gold evidence target beginning `log:docker:` was retrieved through `read_container_logs`. The actual 30-line cap and 300-character rendering limit remained in effect. All 23 corresponding source lines were returned in full; none was lost to time filtering, line selection or truncation. The `mysql_slow_queries` witness `Query_time: 12.4` was present in a 30-minute request and absent from a one-minute request, matching its historical fixture offset.

## Preserved evidence

The source dataset [eval/v4/dataset.json](../eval/v4/dataset.json) retained SHA256 `22b4fd313b699b844c6b16b1378a22753ddcf2149ec880ca5c92e4b1be71ba1f`. No world, original question, gold, existing tool implementation or active scorer was edited for this task.

[The scoped summary](../eval/v5/legacy-migration/replay-tool-evidence-20261117/summary.json) records the counts, precise residuals, source hash, witness control and checksums of all 35 per-case artifacts. Each artifact retains the exact delivered envelopes and a primary delivered-observation trace. Its separately named `rawWorldTrace` is diagnostic material, not the scoring evidence used by this gate.

The [copied JUnit XML](../eval/v5/legacy-migration/replay-tool-evidence-20261117/junit.xml) is byte-identical to the original build output and records **35 passed, 0 failed, 0 errors, 0 skipped**. The original execution artifacts remain under `build/eval/legacy-replay-preflight-1794847130023`. No running `monitoring-numeric-fixture` containers remained after completion.

```sh
rtk env RUN_LEGACY_REPLAY_TESTS=1 ./gradlew evalRun --tests io.ohgnoy.monitoring.eval.LegacyReplayContractTest --offline
```

The broader orchestration manifest must bind this result to the exact source dataset, field-contract sidecar and built dataset. The built dataset's worlds, questions and gold must match the tested source cases; adding a published answer schema does not excuse changing those observations. A passing replay manifest alone is not approval to start a model campaign: the separate semantic-coverage, protocol, scoring and budget gates still apply.

[The finalized preflight manifest](../eval/v5/legacy-migration/preflight.json) marks this scoped gate passed with no blockers. It verifies that all 35 built scenes match their source scenes in every field except additive `answer_fields` annotations, with original answer-field keys and questions preserved. It binds the tested result to:

- Built dataset SHA256: `b9a64a677b529a0d75384d3c5a5e53d615ec556e32970b65102262864189837a`.
- Field-contract sidecar SHA256: `7984c9d8f7d5bc5ccfb2ca1740609c303dab20a8caaed0e062a6519beb44a72e`.
- Source dataset SHA256: `22b4fd313b699b844c6b16b1378a22753ddcf2149ec880ca5c92e4b1be71ba1f`.

This is a separate AI review and executable tool check, not independent human validation or evidence that these manually derived legacy cases represent production incidents generally.
