The historical 35-case replay evidence remains applicable to the expanded 81-field legacy dataset because its worlds and tool implementations did not change. This is a derived compatibility check, not a new runtime test.

The new dataset SHA256 is `27c8f24c7b34ae59a5e72fabb7c867d27a6e95d1c8b8053f7c5652e44a5a5885`. An independent JSON comparison verified all 35 scenes are identical to the prior built dataset except for appended `answer_fields`; the original 62 complete descriptors remain unchanged prefixes and 19 descriptors were appended. Original questions, worlds, gold and other scene data are identical. The original 62-field request-schema file remains byte-identical.

All 35 historical response artifact hashes and their JUnit XML hash were verified against the existing summary. Recorded replay-test, NumericEvalWorld and PrometheusQueryService source hashes remain unchanged. No Docker worlds, models or paid APIs were invoked for this check.

`eval/v5/legacy-migration/preflight.json` now binds this dataset to the historical replay evidence and explicitly states its limited scope. Its SHA256 is `2ace1b59466b73e6c35e4be2bf9dbf555d164b1590627f73e576eea8e19ac7a3`. The supporting `replay-request-schema-rebinding.json` SHA256 is `32f8f9b54f011922246bcf6584117e5453ecdee6519cb19acd06626e8806ed5f`.

The original preflight manifest is preserved byte-for-byte in `build-history/before-explicit-secondary-b9a64a677b529a0d/preflight.json`, with SHA256 `b03e5b3cca0ea4d49533a0941e64ef838f32d960927286df1f022cf681d50482`. The four-case `semantic-boundary-preflight.json` and all underlying artifacts remain unchanged; that historical manifest retains the original dataset binding. The new derived binding and independent source audit explicitly explain why its unchanged-world boundary evidence also applies to the new dataset. Historical paths inside that manifest describe the artifacts at execution time, not a new test of the expanded prompt.

This replay check does not independently approve the semantics of the 19 new descriptors, numerical extraction, model responses or execution. Those remain separate source-audit, adapter/scorer and protocol gates.
