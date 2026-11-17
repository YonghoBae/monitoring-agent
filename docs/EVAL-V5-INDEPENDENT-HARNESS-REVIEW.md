# Independent v5 harness and verifier review

Reviewed 2026-11-17, without reading semantic-holdout cases/labels or making model/API calls. This review made no changes to judge, numeric-contract, runner, world, or frozen datasets. Numeric v1.0 findings below came from new synthetic adversarial strings, after its initial implementation freeze. The reviewer authored numeric v1.0 earlier; its adversarial review is therefore a separate test pass, not independent authorship.

## Material findings

### 1. Semantic validation permits a positive verdict for an empty or unanswered answer

`scripts/semantic_judge_v5.py:38–57` checks quote substring membership, but the empty string is a substring of every answer. It does not require a nonempty quote for a satisfied finding or cross-check `answer_status=unanswered` with satisfaction/pass. It also accepts an empty observation-ID list for a satisfied factual finding. These gaps permit output that violates explicit system-prompt invariants to be accepted as valid.

Local reproduction, using a synthetic required finding `disk` and no observations:

```python
payload = {"answer": "", "reference": {"required_findings": [{"key": "disk"}]},
           "observations": []}
result = {"pass": True, "unsupported_claims": False, "answer_status": "unanswered",
          "findings": [{"key": "disk", "satisfied": True, "answer_quote": "",
                        "observation_ids": []}], "reason": "test"}
validate(result, payload)  # Accepted, pass=True.
```

The same result is accepted for answer `Plans to investigate later.` with status `unanswered`, and answer `Disk is healthy.` with status `answered` while retaining the empty quote and absent observations.

Required amendment: enforce deterministic empty-answer and status/quote consistency before answer scoring. Do not blanket-require observation IDs for every unknown finding: explicitly acknowledging missing evidence can legitimately satisfy an unknown reference. Grounding validity still requires semantic assessment. Preserve the initial frozen code/prompt and validation campaign; record the structural amendment separately.

### 2. Recorded evidence differs materially from the observation the agent actually saw

`NumericEvalWorld.java:73–90` records intercepted raw Prometheus responses before service formatting. `compact()` at lines 195–203 retains only first, middle, and last samples when a range has more than four samples. Conversely, `PrometheusQueryService.java:254–277` returns the first 20 series, including full-range minimum, maximum, latest value, and trend, to the agent.

Consequences run in both directions:

- A peak between the three retained samples is removed from judge evidence, although the agent saw its maximum in the returned summary. Correct observed claims can appear unsupported.
- Raw evidence retains series beyond the 20-series tool-output cap. The judge can see values/entities the agent did not see and mistakenly ground a lucky guess.
- Hardware/system tools round or summarize raw results; raw API data is not an exact record of those delivered tool outputs.

Required amendment: record the exact delivered tool-result envelope and use it as primary semantic evidence. Keep raw API data as separately labeled diagnostic/source material, not as a substitute for the reached observation. This is a correctness blocker for claims of judging only what an agent actually reached.

### 3. Equal tool limits have unequal stopping and final-answer treatment

The arms share nominal limits of 12 tool calls and 90 seconds, but enforcement paths differ. `AgentExecution.java:98–100` throws `Stopped` on the 13th tool attempt. Production/compact run the entire model call through `execution.call()` and convert the stopped execution into `execution.finish(...)`, which returns a partial result. In contrast, `HarnessComparisonRunner.java:101` catches that exception inside the Pi HTTP bridge and returns ordinary `TOOL_ERROR` text. Pi can continue generating and its final text is returned directly at lines 114–115, bypassing `execution.finish()`.

Timeout handling also differs: Pi is killed at line 112 and the runner records an empty answer/error; production/compact return partial observations. Thus scoring near exhaustion conflates harness quality with different answer retention and stop policies. The successfully executed tool count remains bounded; the defect is not an unbounded number of successful tool invocations.

Required amendment: define and enforce the same terminal budget-exhaustion and partial-answer policy for all arms, or explicitly report this as an experimental difference rather than an equal-policy comparison. Token limit 1536 is per completion, not a total investigation token budget; avoid claiming equal total inference tokens without usage accounting.

### 4. Numeric v1.0 accepts unsupported compound-unit prefixes and separated signs

Synthetic offline probes against the frozen numeric v1.0 implementation:

| Verbatim answer/quote | Expected | Actual result |
| --- | --- | --- |
| `8 GB·s` | 8 GB | pass, matched `8 GB` |
| `8 GB*second` | 8 GB | pass, matched `8 GB` |
| `8 GB\\s` | 8 GB | pass, matched `8 GB` |
| `- 8 GB` | 8 GB | pass, matched `8 GB` |

The unit regex rejects a limited set of suffix characters and `/` or `per`, but other compound-unit notation can be discarded. The number regex can also skip a sign separated by whitespace. This violates the documented fail-closed policy for unknown/ambiguous units and values. These are parser defects, distinct from semantic quantity association.

Required amendment: reject unsupported unit continuations and separated or malformed signs instead of accepting a valid-looking substring. Add these synthetic cases to contract tests and version/hash the amended implementation before answer scoring. Do not rewrite the initial frozen implementation identity or tune tolerances against evaluation answers.

## Scope and verification

Read-only inspection covered `semantic_judge_v5.py`, `validate_semantic_v5.py`, `HarnessComparisonRunner`, `NumericEvalWorld`, `AgentExecution`, `ConversationAgent`, `ReActAgent`, `FocusedInvestigator`, `PrometheusQueryService`, and the Pi bridge extension. Executed only synthetic Python probes for findings 1 and 4. Harness findings are supported by the inspected control/data flow; no paid comparative runs or Java integration runs were performed for this review.

Shared model, temperature, per-completion output limit, randomized arm order, frozen observation clock, and the successful tool-call cap are present. The findings above concern observable verifier correctness and comparison policy, not requests to expand benchmark scope.

## Authorized numeric amendment after review

After delivering this review, the coordinator authorized a structural numeric amendment. Original v1.0 code, tests, hashes, and passing test counts were first preserved in `eval/v5/numeric-contract-v1/manifest.json` and its adjacent `scripts/` snapshot. Numeric v1.1 rejects the compound-unit continuations and malformed/separated signs reproduced above, with conservative attached-letter handling. The active module and tests passed 14 methods and 110 parameterized subtests, with zero failures/errors. No semantic-holdout labels or evaluation answers were consulted, and no tolerance was changed.

- Active numeric v1.1 SHA256: `f9d00fdac070a321bd39e631191ebc02b09026dbed84ec298d0493ccbe254381`
- Active tests SHA256: `53910abaee1761c267ed89bea1af0e64af97e7f4d5b6b7aecc0b430bb2dc8b28`

Findings 1–3 were not changed by this reviewer. Their subsequent disposition belongs to the coordinator's implementation/validation record.
