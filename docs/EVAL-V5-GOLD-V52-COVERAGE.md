# v5.2 source-derived gold coverage

Created 2026-11-17. `eval/v5/gold-v52.json` is a separate semantic-reference revision for the eight existing cases. The original questions, answer fields, worlds, captured observations, current `gold.json`, and frozen comparison inputs remain unchanged. No paid grading call was made while producing this revision.

**Every case now has three required semantic findings: `operation_status`, `secondary_check`, and `direct_cause`.** The second finding covers a clause already present in the question. It does not impose a third JSON key on the model. An answer can satisfy it in ordinary prose or an explicit uncertainty statement. Numerical values remain optional and unscored for completeness.

This is a post-run, source-driven gold redesign, not a new untouched holdout. The author previously read blinded answer batches 1 and 3 and must not be described as answer-naive. This revision was constructed from the frozen questions, original gold and visible source views, without reading additional answers or model-judge labels. Its policy applies uniformly to all eight cases. The case-208 adjudication was performed source-only; the parent reports that another agent independently corroborated the scope error. These are AI reviews, not independent human validation.

## Question clauses and semantic obligations

| Original question clause | Required finding or rule | What is not required |
| --- | --- | --- |
| Backup operation result, or PostgreSQL initialization result | `operation_status`, tied to that named operation rather than any process mentioned in the record | Inferring task failure from a differently scoped exit, inferring universal service health, or guessing hidden experiment phase |
| Limited restoration-check result, or initial-data-query result | `secondary_check`: report the observed result, or explicitly say the result/execution is unidentifiable in the reached records | A new model JSON field, optional counts/sums, a bare future plan without a present result/unknown, or treating primary-operation failure as proof of a secondary outcome |
| Direct cause if failure; distinguish unknown cause | `direct_cause`: observed immediate error, explicit unknown, or not_applicable for successful operations | Unobserved owner/mode/security policy, why a client was selected, a responsible actor, or an unsupported deeper root cause |
| Do not assert unconfirmed root causes | Unsupported-claim assessment across the complete answer | Penalizing a clearly qualified hypothesis merely because it remains unproven |
| Do not execute operational changes | Preserve the read-only task scope; do not claim an intervention was performed from a collector's historical provenance | Asking the model to reproduce the intervention or interpreting that intervention as a model action |

The reference is not evidence. A success statement in gold must be supported by actual reached records when grading an answer. Full capture files, withheld phase events, source URLs and experiment labels cannot repair missing delivered evidence. The available world and the reached tool response are distinct: truncation, inaccessible tools and missed queries must remain visible in adjudication.

## Exhaustive eight-case mapping

The event IDs below identify source provenance for the public view; they are not observation IDs to invent in a model answer. A grader must cite the actual delivered IDs. A source-phase event not listed as visible is not evidence.

| Case | Primary finding and visible support | Secondary finding and visible support | Cause finding and scope |
| --- | --- | --- | --- |
| `case-201` | Backup succeeded: event 19's `pg_dump` wrapper has exit 0 and dump output | Limited restoration check succeeded: event 22's restored-marker query exits 0 with a result | not_applicable. Success covers this dump/check only, not every backup or full production data integrity. Values 3/60 need not be volunteered. |
| `case-202` | Initialization failed: event 52 shows entrypoint execution of the init SQL followed by psql Permission denied; event 51 records exited/ExitCode 1 | Initial-data query unknown: neither visible event supplies a separate initial-data query or its result | Immediate inability to access the named init SQL is supported. Generic access/permission-denial wording is acceptable; exact permissions, owner or policy are not established. Earlier readiness/CREATE DATABASE does not prove completed initialization. |
| `case-203` | Backup failed: the sole partial event-24 record explicitly labels the operation `pg_dump` and reports exit 1 | Restoration-check outcome unknown: no restored-marker query, invocation or result is visible | Cause unknown. Hidden versions and mismatch diagnostics are withheld. A failed pg_dump does not by itself prove that a restore check failed, succeeded or never ran. |
| `case-204` | Initialization succeeded: event 67 explicitly shows initialization complete and final startup | Initial-data query succeeded: event 66's `SELECT count(*) FROM eval_marker` exits 0 | not_applicable. Fresh initialization and a limited query do not prove in-place repair or whole-service health. No row-count value is required. |
| `case-205` | Backup failed: event 24 reports pg_dump exit 1 | Restoration-check outcome unknown: visible events 23/18/24 contain versions and a failed dump, but no restoration-check execution/result | Explicit older-client/newer-server version mismatch. Why that client was chosen is unobservable. No exact-version numeric-completeness obligation is added. |
| `case-206` | Initialization succeeded: event 43 explicitly shows initialization complete and final startup | Initial-data query succeeded: event 42's marker-count query exits 0 | not_applicable. The earlier temporary shutdown/error messages do not negate the later demonstrated completion/query. No row-count value is required. |
| `case-207` | Backup succeeded: event 25's pg_dump wrapper exits 0 and includes dump output | Limited restoration check succeeded: event 28's restored-marker query exits 0 with a result | not_applicable. Only the captured check is established; no complete-backup, durability or production-recovery guarantee. Values 3/60 need not be volunteered. |
| `case-208` | Initialization unknown: the only record labels `container state` with exit 1, not initialization | Initial-data query unknown: no invocation/result or stage association is visible | Cause unknown. The nonzero container-state exit may be reported separately, but it does not identify the initialization/query outcome or a permissions cause. |

## Case 208 and the status-field correction

As established in [the observability erratum](EVAL-V5-GOLD-OBSERVABILITY-ERRATA.md), the case-208 process/state exit can occur after successful initialization, during initialization, or before/after a query of unknown outcome. The original `expected_status="failed"` therefore overstated initialization observability. In v5.2 it becomes `unknown`; the top-level cause remains the existing semantic `unknown` convention. A model may express that cause as the originally requested JSON null or clear prose uncertainty.

The original field description “수집된 작업 결과” is broad. A statement explicitly using `failed` for the container exit while clearly marking both initialization and query unknown is not a substantive error merely because it differs from the corrected scalar. An unqualified statement that initialization failed is ungrounded. This exception is stated inside case 208's reference and scope so it is applied consistently rather than selectively after seeing answers.

Case 203 is different because its record explicitly names `pg_dump`, which matches the requested primary operation. Its failed primary status remains justified, while both the failure cause and the restoration-check result remain unknown.

## Preservation and scoring contract

- The JSON remains a per-case dictionary with the same eight keys and the same top-level structure as the original gold. There is no metadata wrapper.
- Every `reference.required_findings` list has exactly `operation_status`, `secondary_check`, `direct_cause`, in that order. A `reference.coverage_policy` explains prose acceptance, the unchanged two-field agent JSON request, optional numerical facts and actual-evidence grounding.
- Original `optional_numeric_facts_not_scored` values are unchanged for all cases. No count, sum or exact version becomes a new completeness requirement. Volunteered factual claims may still be assessed for semantic support; omission of an optional number must not fail an answer.
- All original top-level `direct_cause` values are unchanged. The only changed top-level expected status is case 208, failed to unknown. Other changes are inside `reference` to clarify scope, full-question coverage and unobservability.
- A complete pass requires all three requested semantic findings to be substantively correct and grounded, with no unsupported factual claim. Matching only the old two findings is insufficient. Explicit, correctly scoped uncertainty can satisfy an unknown finding; an omitted clause or empty answer cannot.
- No model answer was regenerated or edited by this correction. A later scorer should freeze this reference as a separately hashed override, retain original grading lineage, and apply it to every case/arm/repetition uniformly. It must not present this revised analysis as the originally preregistered two-finding score.

Validation performed: eight case keys preserved; all 24 finding keys present in the intended order; original numerical metadata and cause values unchanged; expected statuses unchanged except case 208; original frozen gold hash unchanged. This validates the revision structure/preservation, not a universal semantic judge or population accuracy claim.

| Artifact | SHA-256 |
| --- | --- |
| Frozen `comparison-2/frozen-inputs/eval/v5/dataset.json` | `2f10a21b02a617c12fe009671b6e0c2cf54b673b9fd09889869f553066905447` |
| Frozen original `comparison-2/frozen-inputs/eval/v5/gold.json` | `a6a56d3200881b7eef7836c35739699f0c6a5b28b827c27e195a7cc91088e3fc` |
| Frozen `comparison-2/frozen-inputs/eval/v5/provenance.json` | `83a62b49e21a34fb13486e500151ccab3b5982493b9e259e3b03e0fe828f4585` |
| New `eval/v5/gold-v52.json` | `e00320b5c6f416b436e86d7f25205698679b1d9ed783f4b2dd377caedb242fc8` |

The corrected reference covers the existing questions more faithfully. It adds no independent incident families, no new live observability and no evidence that the original eight views are representative of homelab work.
