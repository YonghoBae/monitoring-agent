The confirmatory canonical core is prepared but has not started. The exploratory `eval/v5/comparison-2` campaign requested two structured fields while its question and amended rubric covered three results. Its answers and scoring remain historical exploratory evidence. This new collection requests all three results before generation; it does not repair or replace those earlier answers.

`scripts/build_canonical_core_v5.py` created `eval/v5/canonical-core/dataset.json` with SHA256 `4125f2c74f9308b6d2ff57b25e30d724bcb54eca92528ab436067516e1c44edc`. All eight IDs, original questions, worlds, families, splits and other scene properties are identical to the original dataset. Only `answer_fields` changes. The separately stored original provenance remains unchanged. Each family has the same three neutral descriptors across all phases:

- `operation_status`: the backup or PostgreSQL initialization phase itself, distinguished from generic container state; unknown is permitted.
- `secondary_check`: the observed limited restore check or initial-data query result; absent or inconclusive observations permit unknown. No row count, checksum or specific answer is disclosed.
- `direct_cause`: the immediate observed failure cause; success permits not_applicable and unavailable cause or result permits unknown. Unobserved underlying causes must not be asserted.

The approved `gold-v52.json` SHA256 remains `e00320b5c6f416b436e86d7f25205698679b1d9ed783f4b2dd377caedb242fc8`. The original dataset SHA256 remains `2f10a21b02a617c12fe009671b6e0c2cf54b673b9fd09889869f553066905447`, and the original gold file was not edited. Original numeric metadata is unchanged; this campaign continues semantic assessment without adding arithmetic or numeric-format requirements.

`scripts/run_canonical_core_v5.py` defaults to a filesystem-only `check`. It requires a root-approved protocol and frozen scoring manifest; it never creates approvals or warms a model. Explicit `run --execute` first checks `/api/tags` and `/api/ps` for the already-loaded model `qwen3.5:9b-pi32k`, digest `2872f35f2b99c438d19beb6cfaf7002a3150f04c0d850542ca52a554414c233f`. It then calls the existing `HarnessComparisonRunner` with the canonical `EVAL_DATASET`, two enhanced arms and three repetitions. Its expected 48 rows follow the existing within-family ordinal-plus-repeat policy: each arm starts 12 pairs overall, six in each family and four in each repeat. Duplicate, missing or reordered rows fail validation. Explicit runner errors remain rows in the denominator.

The campaign manifest records the actual repository-relative `dataset_path`, source snapshots, model metadata, order plan and hashes. It archives exact delivered tool envelopes as primary evidence; raw world traces are not substituted. Inputs are checked again after collection. Full and partial raw outputs are preserved, including an incomplete runner with no completion marker. Existing output directories cannot be overwritten or silently retried.

`scripts/score_canonical_core_v5.py` is a separate derivative of the existing v52 scorer. The old scorer and original validated `semantic_judge_v5.py` are unchanged. It requires the original independent v52 gate to pass 20 cases / 60 judgments, uses the manifest's frozen canonical dataset and the approved frozen gold, and rejects any scene whose three requested keys do not match all scored findings. It retains two judge verdicts per answer, exact delivered observations, arm-blinded payloads, full denominators, and unresolved nonpass for scored-label disagreement or invalidity. Paid grading requires explicit CLI `run --execute` and registered budget approval.

Root registration must create `eval/v5/canonical-core/protocol.json` with these fields:

```json
{
  "status": "approved",
  "benchmark_kind": "confirmatory_canonical_core",
  "arms": ["pi_plus", "compact_plus"],
  "repeats": 3,
  "expected_answers": 48,
  "case_ids": ["case-201", "case-202", "case-203", "case-204", "case-205", "case-206", "case-207", "case-208"],
  "dataset_path": "eval/v5/canonical-core/dataset.json",
  "dataset_sha256": "4125f2c74f9308b6d2ff57b25e30d724bcb54eca92528ab436067516e1c44edc",
  "gold_path": "eval/v5/gold-v52.json",
  "gold_sha256": "e00320b5c6f416b436e86d7f25205698679b1d9ed783f4b2dd377caedb242fc8",
  "order_policy": "within-family-ordinal-plus-repeat-rotation-v1",
  "generation": {"temperature": 0, "max_output_tokens": 1536, "reasoning_effort": "none"},
  "limits": {"uncached_tool_calls": 12, "timeout_seconds": 90},
  "model": {
    "name": "qwen3.5:9b-pi32k",
    "digest": "2872f35f2b99c438d19beb6cfaf7002a3150f04c0d850542ca52a554414c233f",
    "base_url": "OPERATOR_SELECTED_ENDPOINT"
  },
  "scoring_manifest": {"path": "eval/v5/canonical-core/scoring-gate.json", "sha256": "REGISTER_AFTER_REVIEW"}
}
```

The scoring manifest must have `status: "frozen"`, `validation_hashes` equal to the hashes of the original v52 validation `manifest.json` and `summary.json`, and `frozen_hashes` covering all `score_canonical_core_v5.SCORING_INPUTS` plus the canonical dataset, builder and driver. Register `eval/v5/canonical-core/scoring-1` in the paid-campaign registry before freezing its hash. The driver also snapshots the protocol, source, original gold, provenance, reproduction files and relevant Java/build/tool-fixture files. Collection goes to `canonical-core/comparison-1`; scoring goes to `canonical-core/scoring-1`.

Offline verification on 2026-11-17: 21 tests passed via `python3 -m unittest discover -s scripts/tests -p '*canonical_core_v5.py' -q`. Tests cover source invariance, identical descriptors across phases, refusal to overwrite, correct phase/request alignment, order and evidence rejection, approval/model/hash gates, canonical manifest-path validation, synthetic full and partial collection, scorer evidence isolation, disagreement handling, and denominator preservation. No benchmark answers, inference endpoints or paid APIs were used. The actual default check returned `blocked_not_started` because the root protocol was not yet registered; this is the intended pre-registration state.

These eight views still represent only two mechanism families. Repetitions and synthetic views do not establish general home-server incident performance or an independent sample of 24 incidents per arm. Report scoped results and uncertainty without forcing a general leaderboard.
