# Independent numeric contract review

The frozen numeric contract v1.1 has two independently reproduced fail-closed gaps. These block a claim that it is ready for broader numerical scoring without correction and renewed validation. They do not require changing the current v5 comparison, whose registered scoring is semantic only.

The reviewer authored synthetic controls without accessing benchmark answers or invoking a model API. The reviewer did not author the parser. This is a separate AI review, not human validation or independence from shared AI biases. The frozen [numeric_contract.py](../scripts/numeric_contract.py) remained unchanged, with SHA256 `f9d00fdac070a321bd39e631191ebc02b09026dbed84ec298d0493ccbe254381`.

## Frozen v1.1 findings

[The independent test file](../scripts/tests/test_numeric_contract_independent.py) initially ran 16 test methods against v1.1. Fourteen methods passed. Two methods produced six failing subtest assertions, with no execution errors or skips. The failures were not suppressed or reclassified as successes.

| Synthetic input | Required result | Frozen v1.1 result |
| --- | --- | --- |
| `8 GB h` against 8 GB | Ungradable | Pass |
| `8 GB min` against 8 GB | Ungradable | Pass |
| `8 GB-second` against 8 GB | Ungradable | Pass |
| `{"free":8,"unrelated":NaN}`, binding `free` to GB | Ungradable | Pass |
| `{"free":8,"unrelated":Infinity}`, same binding | Ungradable | Pass |
| `{"free":8,"unrelated":-Infinity}`, same binding | Ungradable | Pass |

Space-separated unit products and hyphenated unit names must not be silently reduced to their recognized GB prefix. The existing suffix filter detects only its supported adjacent units and a selected set of multiplication/division operators. It misses these additional unit products.

The binding contract requires a complete JSON object. NaN and infinities are not JSON values, including when they occur outside the selected field. The parser's `parse_constant` callback converts them into Python `None`, allowing an otherwise invalid object to pass when the selected field is finite. This is distinct from correctly rejecting a nonfinite selected field.

The passing controls cover SI versus IEC labels without repair; exact duration conversion and tolerance boundaries; maximum rather than summed tolerance allowances; negative and zero targets; explicit tolerance for rounded binary values; rate versus count and stored-amount dimensions; equivalent and conflicting restatements; unsupported unit labels; scientific and grouped values; exact root-field schema binding; structural window checks; and the separation of numerical correctness from semantic association and observation support.

These tests do not validate quantity identity, event identity or evidence grounding. A correctly normalized scalar remains insufficient to prove that an answer addresses the requested measurement. Existing `semantic_association`, `evidence_grounding` and unprovided window checks correctly remain `not_assessed` in the passing controls.

## Draft correction status

A separate [numeric_contract_v12.py](../scripts/numeric_contract_v12.py) draft corrects these findings. Its version is `1.2-draft`; it is not the active comparison scorer. The frozen parser and active comparison remain unchanged.

The draft rejects hyphen/dash unit continuations and recognizes additional conventional unit atoms solely to reject unsupported compound products. That rejection list does not add those atoms to supported scoring units or authorize conversions. Strict JSON parsing now rejects NaN and infinities anywhere in the quoted object instead of replacing them with null.

The independent file now explicitly imports the draft. Its original 16 methods plus one additional method guarding ordinary prose and suffix rejection **pass 17/17**, with no errors or skips. The original author's 14 contract methods also pass when their grading function is explicitly replaced with the draft's function for this audit. That second check is a compatibility check, not an additional independent test set. Draft SHA256: `b809f37fd1d18b6c7b3e8924e3b00d7bcf1ca1b7b81f41eee0ca6f3f8ae24bab`.

Run the draft controls from the repository root:

```sh
rtk python3 -m unittest discover -s scripts/tests -p test_numeric_contract_independent.py -v
```

The original frozen-parser failures remain reproducible by explicitly substituting v1.1 and selecting the original 16 methods:

```sh
rtk proxy python3 - <<'PY'
import sys
import unittest
sys.path[:0] = ["scripts", "scripts/tests"]
import test_numeric_contract_independent as controls
from numeric_contract import grade_numeric
controls.grade_numeric = grade_numeric
suite = unittest.defaultTestLoader.loadTestsFromTestCase(
    controls.IndependentNumericContractTests
)
suite = unittest.TestSuite(test for test in suite
    if test._testMethodName != "test_draft_suffix_rejection_preserves_ordinary_prose")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
PY
```

That command is expected to fail with the six recorded subtest assertions. It must not be presented as passing v1.1 validation.

## Remaining scope limits

The draft fixes the reproduced suffix forms; a finite suffix recognizer is not a proof of correct interpretation of every possible unit spelling in unrestricted prose. The test outcomes support these focused controls and should not be generalized into a population error rate.

The API still requires explicit expected units. JSON binding supports a named root scalar only; nested `/facts/key` mappings need an explicitly implemented and separately tested contract. This draft adds no days, temperature or CPU-core units, and does not define HTTP status-code identity. A migration sidecar alone cannot supply parser behavior that is not implemented.

For broader legacy scoring, freeze any further mapping and parser extension, validate it before viewing evaluation answers, and report unsupported cases explicitly. The current semantic-only v5 comparison remains governed by its existing frozen protocol. No numerical result from this draft has been applied to its answers.
