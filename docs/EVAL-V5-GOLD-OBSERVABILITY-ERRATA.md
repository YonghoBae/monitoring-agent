# Gold observability erratum: case 208

Source-only independent AI adjudication, 2026-11-17. This review read the frozen `comparison-2/frozen-inputs/eval/v5/{dataset,gold,provenance}.json` definitions for cases 203/208 and their original collector events. It did not inspect current answers, batch 4, private mappings, comparison results or Haiku judgments. No frozen input was modified.

**Finding: case 208 does not expose enough evidence to label PostgreSQL initialization or the initial-data query as failed.** The record reports a nonzero exit code under `container state`; the requested initialization and query outcomes remain unknown. The original `expected_status="failed"` conflates a process/state observation with the outcome of the workflow asked about. The original cause-unknown label is appropriately cautious, but making only the cause unknown is insufficient.

This corrects my earlier provenance review's acceptance of case 208 as “known failure, unknown cause.” The capture/source mapping is real and the value is preserved, but I failed to verify that the visible operation identity matched the question's operation. The earlier local test checked the code and absence of a cause leak; it did not prove this semantic entailment. Its pass is not a reason to retain the overstated gold.

## Frozen evidence and its scope

Case 208 asks for “PostgreSQL 초기화와 초기 데이터 조회 결과” and requests operation status plus direct cause. Its only log record is:

```json
{
  "operation": "container state",
  "exit_code": 1,
  "detail": "Detailed output is unavailable in this view."
}
```

The remaining public world contains the alias `service-db`, an observation clock and no metric series or RAG content. A container name establishes identity, not whether initialization succeeded. The question identifies what the user wants investigated; it does not assert that the visible exit happened during initialization. Neither the filename of the experiment nor the hidden family/phase label can supply that missing link.

The producer extracted `.State.ExitCode=1` from collector event 51. The original Docker inspect command itself succeeded with exit code 0. Its raw state also records an exited container, but the public partial record drops the explicit `Status`, timestamps and context. Thus `exit_code=1` in this wrapper is not the inspect command's exit status. That collector knowledge explains the transformation; it is not reached evidence that initialization failed. The wrapper would be clearer with a named `container_exit_code` field and explicit state in a future version.

Even accepting the intended interpretation that the container process exited nonzero, the record is compatible with several histories:

- Initialization failed before any initial-data query.
- Initialization and the initial-data query succeeded, then a later process failure caused the container exit.
- Initialization succeeded, but the query was never executed or its result was not collected before the exit.

These are logical alternatives, not diagnoses of the actual captured run. One alternative consistent with the visible record is enough to show that initialization failure is not entailed. The hidden SQL error in event 52 and the `init-fault` collector name would resolve the historical run, but neither is visible in case 208.

## Source-justified reference for case 208

The exact intended answer should distinguish the observed exit from the unobservable requested work:

> 수집된 컨테이너 상태 기록에는 exit_code 1이 표시되어 있습니다. 이 기록만으로는 PostgreSQL 초기화가 성공했는지, 초기 데이터 조회가 수행되었거나 성공했는지 확인할 수 없습니다. 비정상 종료의 직접 원인도 확인되지 않습니다.

The term “비정상 종료” follows the producer's intended container-exit interpretation. The most literal rendering can simply say “컨테이너 상태 기록의 비영(1) 종료 코드” without claiming an exact process stage. Do not reinterpret the record as proof that the inspection tool failed either: the visible label is underspecified, and source event 51 shows a successful inspection.

A future unambiguous reference should use distinct findings:

```json
{
  "required_findings": [
    {
      "key": "container_observation",
      "statement": "The visible container-state record reports exit_code 1; it does not identify the failing workflow stage."
    },
    {
      "key": "initialization_status",
      "statement": "Unknown: the reached record does not establish whether PostgreSQL initialization succeeded or failed."
    },
    {
      "key": "initial_data_query_status",
      "statement": "Unknown: the reached record does not establish whether the initial-data query ran or its outcome."
    },
    {
      "key": "direct_cause",
      "statement": "Unknown: no diagnostic identifies the cause of the reported nonzero exit."
    }
  ]
}
```

If the existing two-field interface must be retained, use `operation_status="unknown"` for the requested initialization/data-query work and `direct_cause=null` (semantic unknown), while retaining the observed nonzero container-state code in prose. An answer that uses `failed` explicitly for the **container exit** but separately says **initialization and query outcomes are unknown** should not be rejected solely for its scalar label. The old field description “수집된 작업 결과” does not identify the operation precisely enough for that exact-match rule. Conversely, an unqualified “initialization failed” is not made grounded by matching the old gold.

This correction changes the scope of the required status, not the original capture. It does not authorize inventing a successful initialization, naming a permissions cause, inferring a database count, or treating absent diagnostics as evidence of normality.

## Why case 203 differs

Case 203 asks for the backup operation and its limited restoration check. Its visible record is:

```json
{
  "operation": "pg_dump",
  "exit_code": 1,
  "detail": "Detailed output is unavailable in this view."
}
```

Here the operation label directly names the requested backup-producing command. A nonzero exit supports “the recorded pg_dump backup attempt failed.” It does not expose the mismatch diagnostic, so the direct cause is unknown. It also supplies no restoration-check result. The complete source-justified reference is:

> 기록된 pg_dump 백업 시도는 exit_code 1로 실패했습니다. 상세 오류가 없어 직접 원인은 확인할 수 없습니다. 해당 덤프의 제한적인 복원 검사가 수행되었는지 또는 어떤 결과였는지도 이 기록만으로는 확인할 수 없습니다.

Thus case 203 can retain `operation_status="failed"` when explicitly scoped to the backup attempt. A separate restoration-check unknown is needed to answer the whole question. The original two required findings omit that question clause; a two-field match alone must not certify completeness. No failure cause or restoration outcome may be imported from the hidden source phase.

## Handling the frozen comparison

1. Preserve the original frozen input and its original score lineage. Attach this erratum as a versioned, source-derived correction; do not overwrite the old gold or silently relabel recorded results.
2. Do not use case 208's original failed-status gold as a reliable measure of correct initialization diagnosis. Exclude that original status assessment from an unqualified ranking, or explicitly mark it invalid pending corrected semantic adjudication.
3. If regrading existing answers, apply the corrected operation scope and the full-question completeness rule uniformly, with arm/repetition labels hidden. Report original and corrected criteria separately; disagreements remain explicit. This source review does not determine how any answer should score.
4. For a future dataset, either keep the current sparse container-state record and ask for stage uncertainty, or expose a genuine record identifying initialization as the failed operation. Adding such information changes the observation task and requires a new dataset version. Do not insert a synthetic “initialization failed” label merely to preserve the previous answer.
5. Add independent semantic checks that distinguish an observed process exit from outcomes of earlier workflow stages, and separately cover every question clause. Byte preservation, source hashes and correct phase mappings remain necessary but do not establish answer observability.

Reviewed frozen hashes:

| Input | SHA-256 |
| --- | --- |
| `comparison-2/frozen-inputs/eval/v5/dataset.json` | `2f10a21b02a617c12fe009671b6e0c2cf54b673b9fd09889869f553066905447` |
| `comparison-2/frozen-inputs/eval/v5/gold.json` | `a6a56d3200881b7eef7836c35739699f0c6a5b28b827c27e195a7cc91088e3fc` |
| `comparison-2/frozen-inputs/eval/v5/provenance.json` | `83a62b49e21a34fb13486e500151ccab3b5982493b9e259e3b03e0fe828f4585` |

The corrected conclusion is narrower than the prior review: provenance is intact, but case 208's initialization-status observability was overstated. This is a gold-design defect, not evidence of an agent reasoning failure.
