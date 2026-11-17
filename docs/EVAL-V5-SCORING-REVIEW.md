# V5 scoring review and corrections

Reviewed before actual comparison answers existed. No actual answers or semantic-holdout labels were read, and no paid calls were made. Review covered `score_eval_v5.py`, `run_eval_v5.py`, the frozen-protocol draft, shared API accounting, required gold field names, and delivered-evidence capture. The coordinator subsequently authorized the corrections below; the corrected implementation must be frozen before comparison execution.

## Findings and disposition

1. **Comparison and judge repetitions were validated by count rather than identity.** A synthetic offline reproduction supplied 48 identical case/arm/repetition rows and two copies of judge repetition 0. The original implementation accepted preparation and reported 48 stable passes. The corrected runner and scorer require the exact eight-case × two-arm × three-repetition grid. Summary requires distinct judge repetitions 0 and 1; missing, duplicate, invalid, and disagreeing judgments remain unresolved nonpasses. Unknown answer IDs stop summarization. Every arm retains its 24-answer denominator, including runner errors.

2. **The $2 cap was local to an output directory plus a fixed prior.** A second arbitrary scoring directory could omit prior scoring costs or uncertain requests. `eval/paid-campaigns.json` now explicitly registers the two historical campaigns, semantic validation, and `eval/v5/scoring-1`. `budget_registry.py` sums each directory's own completed-request costs once, ignores cumulative manifest priors, rejects duplicate/canonical-equivalent paths and unregistered outputs, and blocks on an unresolved request anywhere. A process lock spans preflight and the paid request. Before each request, the current manifest prior is refreshed to the sum of all other registered campaigns; the existing API client's conservative token reservation then enforces the shared $2 cap. Existing request logs also prevent a silent run replay when no scoring-results row was written.

   Offline registry verification found $0.0367491 + $0.0018732 + $0.0202981 = **$0.0589204** spent, with zero unresolved requests. These remain estimates based on usage, not invoice totals. This guard is the authorized v5 scoring entry point; historical standalone scripts should not be invoked to bypass it.

3. **Recorded scorer/judge hashes were not enforced against the comparison freeze.** Preparation and scoring now verify frozen file contents and compare the current scorer, judge, runner, budget helper, shared API helper, numeric contract, protocol, and explicit paid registry against comparison-time hashes. The prepared mapping and every payload are hashed, and payload identity is checked again immediately before each judgment. The comparison freeze includes the dataset builder and source captures as well as agent/runner code. Changes require an explicit new protocol/freeze; they are not silently accepted during scoring.

4. **The summary omitted the protocol's separate judgment-repeat pass rates.** It now reports both repeats with the fixed denominator, valid-output counts, and conservative pass counts/percentages, alongside stable-pass, family, and agent-repeat results.

## Checks that passed review

- Payloads contain only question/requested fields, answer, reference, and exact delivered observations. Arm, repetition, family, prior scores, and raw-world diagnostic traces remain outside judge payloads. Synthetic tests verify that raw-only sentinel evidence never appears.
- Gold required-finding keys are only `operation_status` and `direct_cause`. Numeric counts are not hidden completion requirements, and the separate numeric contract does not certify old numeric scores.
- Two valid matching semantic verdicts are required for stable pass; disagreements are not repaired. Runner errors are retained as nonpasses, even if semantic verdicts pass.
- Empty answers receive deterministic fail/no-claim. Uncertain API outcomes stop paid calls; partial summaries preserve the full comparison denominator.
- Calibration pass/unsupported labels matched all 60 judgments. Descriptive `answer_status` matched **57/60**; it is excluded from scored agreement and explicitly reported as a limitation. Calibration remains limited evidence, not universal judge certification.

## Verification

`scripts/tests/test_score_eval_v5.py` contains synthetic offline regressions for grid identity, blinding, exact evidence, missing/duplicate/invalid judgments, disagreement, runner-error denominators, frozen-code and payload tampering, cumulative cost accounting, prior uncertain outcomes, arbitrary paths, and a budget reservation that must block before network access. No evaluation answers or holdout labels enter these tests.
