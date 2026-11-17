# Independent source check of v5.2 gold

**No source or coverage blocker was found in the inspected v5.2 gold.** Nine focused tests passed, with no failures, errors or skips. This supports using the revised reference after its separate judge-validation gate passes; it does not certify the judge or any model answers.

The inspected [gold-v52.json](../eval/v5/gold-v52.json) has SHA256 `e00320b5c6f416b436e86d7f25205698679b1d9ed783f4b2dd377caedb242fc8`. The check used only its text, the frozen comparison-2 questions/world, the original gold and frozen-input identity metadata. No collected answers, other reviewer outputs or paid judge results were opened for this check. The reviewer previously reviewed assigned blinded subsets in separate tasks; this is source-only validation of the new reference, not a claim of never having seen any benchmark answer.

## Question coverage and answer requirements

All eight original questions already ask for a primary operation, a separate check, and the direct cause if failure is established. The three required findings now expose that existing coverage directly:

| Original question clause | Required finding |
| --- | --- |
| Backup operation or PostgreSQL initialization outcome | `operation_status` |
| Limited restoration check or initial-data query result | `secondary_check` |
| Direct failure cause, with uncertainty when unobserved | `direct_cause` |

The original requested JSON fields remain `operation_status` and `direct_cause`. The revised reference explicitly allows the secondary result in ordinary prose or an explicit unknowns statement. It does not require an additional JSON key, an exact wording, a row count or a numerical interpretation of the marker query. Optional numeric metadata is retained unchanged and does not become a completeness requirement.

## Evidence and phase boundaries

| Case | Primary operation | Secondary check | Direct cause and evidence boundary |
| --- | --- | --- | --- |
| case-201 | Backup succeeded | Limited restored-marker query succeeded | Not applicable; captured `pg_dump` and query records both have successful exits |
| case-202 | Initialization failed | Initial-data query result unknown | Explicit `psql` permission-denied error while processing the initialization SQL file |
| case-203 | Backup failed | Restoration-check result unknown | `pg_dump` is explicitly named with a nonzero exit, but error detail is withheld |
| case-204 | Initialization succeeded | Initial-data query succeeded | Initialization-complete log plus the separate successful marker query |
| case-205 | Backup failed | Restoration-check result unknown | Explicit client/server version mismatch; the reason that client was selected is unobserved |
| case-206 | Initialization succeeded | Initial-data query succeeded | Initialization-complete log plus the separate successful marker query |
| case-207 | Backup succeeded | Limited restored-marker query succeeded | Not applicable; captured `pg_dump` and query records both have successful exits |
| case-208 | Initialization outcome unknown | Initial-data query result unknown | Only a generic container-state record with a nonzero exit is visible |

Case-202 cannot be classified from a wrapper command's successful exit or an earlier temporary startup alone. The explicit later `psql` error establishes the failed initialization attempt. It supports generic permission/access-denial language; it does not establish owner, mode, ACL, security policy or responsible actor.

Case-208 is materially different from case-203. Its sole operation label is `container state`, not `pg_dump` or an initialization step. The nonzero exit is visible and can be reported as such, but does not establish the success or failure of the requested initialization or separate data query. Changing the requested workflow status to unknown corrects that entity/phase association. A response can report the nonzero container exit while leaving both requested workflow results explicitly unknown.

For cases with no separate check record, unknown is the supported result. Failure of an earlier step does not establish that a later query failed, succeeded or never ran. Successful secondary checks are bounded to the observed query; they do not prove all backup contents, general service health, successful repair of a failed data directory or production recovery.

The reference is not agent evidence. A particular answer may have reached fewer observations than are available in the world. Actual scoring must continue to use its delivered tool observations and cannot use this source audit to credit an unseen result.

## Preservation and reproducibility

The original [gold.json](../eval/v5/gold.json) remains byte-identical to the comparison-2 frozen copy, with SHA256 `a6a56d3200881b7eef7836c35739699f0c6a5b28b827c27e195a7cc91088e3fc`. The original [dataset.json](../eval/v5/dataset.json), including every question and world, remains byte-identical to its frozen copy, with SHA256 `2f10a21b02a617c12fe009671b6e0c2cf54b673b9fd09889869f553066905447`.

All eight `optional_numeric_facts_not_scored` objects remain identical to the original gold. Outside the revised reference text, the only changed field is case-208's `expected_status`, from `failed` to `unknown`; its direct-cause metadata and all other non-reference metadata remain unchanged.

[test_eval_v52_gold.py](../scripts/tests/test_eval_v52_gold.py) checks frozen identities, all eight case IDs, the three reference findings against actual question clauses, the unchanged JSON-field contract, optional numeric preservation, separately observed successful queries, justified secondary unknowns, direct-error boundaries, and the named-backup versus generic-container distinction.

```sh
rtk python3 -m unittest discover -s scripts/tests -p test_eval_v52_gold.py -v
```

Result: **9 passed; 0 failed; 0 errors; 0 skipped**. No source, active scorer, original gold or dataset was edited for this check. No model or paid API calls were made.

This is a post-collection reference amendment and should remain identified as such in reporting, with the original reference and earlier validation failures preserved. The reviewer is a separate AI process, not independent human validation. The result supports the scoped, corrected reference; it does not establish benchmark representativeness or justify relaxing the judge-validation gate.
