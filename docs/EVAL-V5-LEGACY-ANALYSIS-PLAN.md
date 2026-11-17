# Prospective broad comparison analysis plan

Frozen in advance of the first broad 35-case model answer. This comparison is a controlled regression benchmark, not an estimate of naturally occurring home-server incident accuracy. The 35 selected cases belong to 28 families; three model repetitions and two judge repetitions do not create additional independent incidents.

## Outcomes

The primary comparison is **family-macro requested-finding correctness**: for each answer, the fraction of all explicitly requested findings that both valid judgments support, with deterministic numeric correctness additionally required for numeric fields. Average the three runs within each case, then the cases within each family, then the 28 families equally. All 81 published findings are included. Keep the original 62-field score as a separately named compatibility diagnostic, never substitute it for the primary outcome.

Also report the existing case-macro and field-micro scores, all-findings-correct answer count, and strict structured pass. Strict structured pass requires correct and supported requested content, no unsupported claim, valid requested output structure, no runner error, and agreement between both scored judgments. A schema failure is not automatically a factual error; retain content credit and report the format failure separately. Missing or invalid judgments remain in every denominator and contribute no stable correctness. Scored agreement compares combined field labels and strict pass, rather than auxiliary labels that cannot change either endpoint. Show unresolved counts and per-judge results alongside the conservative stable scores.

### v5.5 final validation scope, before any broad model answer

The judge supplies atomic finding labels and an unsupported-claim flag; aggregate pass is computed in code, not asked of the model a second time. The judge, transport, numeric rules, and per-answer composition remain identical to v5.4. The reported endpoints are requested-field correctness and strict complete-answer pass. A fresh independent gate requires exact agreement for both endpoints in every control repetition. Controls with all requested facts correct plus fabricated extra assertions, and correct answers with qualified hypotheses, guard both directions of an unsupported-label error that can change strict pass.

Unsupported-claim assessment has a narrower, explicit scope: only answers whose final JSON parses and whose requested fields conform to the published schema (including its null policy) are assessed. Otherwise the final unsupported value is null/UNASSESSED, and any raw judge flag is diagnostic only. UNASSESSED is never false, never earns unsupported-free credit, and can never yield a strict structured pass. Every answer remains in the denominator. Field correctness still uses the same deterministic numeric AND semantic rule; this clarification does not turn invalid numeric answers into correct ones.

Standalone unsupported labels, unsupported-free rates, their coverage/bounds, and raw semantic labels overridden by deterministic code are retained only as explicitly unvalidated auxiliary diagnostics. Do not use them for ranking or claim a certified hallucination rate. Missing/invalid judgments remain unresolved; an auxiliary disagreement alone is not a scored disagreement if every combined field and strict pass remain identical.

The earlier v5.4 full gate remains failed: its60 final field/pass outcomes matched, but one standalone unsupported label did not. This scope change was made prospectively before any broad answer, and requires fresh controls; it does not retroactively turn that failed gate into a pass. Earlier plan bytes are archived in the migration directory. This is the final measurement definition: do not tune it after broad answers arrive.

## Comparison and uncertainty

Pair the two arms by case and model repetition. Show per-family differences and counts favoring each arm/tied, repeat-specific scores, source-tier scores, and latency/tool-call diagnostics. Do not treat 210 answers or 420 judgments as 210/420 independent scenarios.

For the primary difference (compact minus Pi, percentage points), report a paired family bootstrap sensitivity interval: resample the 28 complete family differences with replacement, 20,000 draws, seed 20261117, equal family weighting, and linearly interpolated 2.5th/97.5th percentiles. This interval describes sensitivity to the selected family mix under exchangeable-family assumptions; it is **not** a population confidence interval for all home servers. With only two actual reproduced fault mechanisms, the separate canonical core receives descriptive paired counts and repeat ranges, not a misleading incident-level confidence interval.

There is no general final harness ranking. Within this fixed broad benchmark, describe one arm as clearly ahead only if the primary sensitivity interval excludes zero, every model repetition has the same direction, and the direction survives a conservative unresolved-judgment sensitivity check. That check replaces every unresolved answer's finding fraction with 0 for the apparent leader and 1 for the other arm, then recomputes the same family-macro difference. Otherwise state that the benchmark does not establish a stable ordering. Failure to establish an ordering does not prove equivalence.

## Integrity and reporting

Publish the canonical core and broad controlled regression separately. Never merge their denominators or compare the new score directly with historical 76.7 as an improvement estimate: question visibility, gold coverage, and grading differ. Keep aborted runs and failed judge validations in the provenance and cost totals. Independent reviewers are AI subagents, not independent humans; shared-model and source-selection biases remain possible.

Do not tune harness prompts, reference answers, tolerances, output schema, or scorer based on the collected broad answers and then score those same answers as a fresh confirmatory test. Any subsequent improvement needs a newly labeled development stage and a separately frozen test.

## Independent answer audit sample

Before collecting broad answers, select model repetition 0 for both arms in every one of the35 cases:70 of210 answers, covering every question and family. Shuffle and replace identifiers before two independent AI reviewers inspect35 answers each. Provide the published question/fields, frozen semantic reference, and exact delivered tool observations; withhold arm identity, automated judge verdicts, and the other reviewer's judgments. Preserve per-finding decisions, unsupported-claim flags, and explicit ambiguity notes. Compare this audit with automated scoring only after independent reviews are saved. Do not overwrite automated scores or silently remove ambiguous/disagreeing answers. Additional targeted failure review is diagnostic and must not be confused with this prospectively selected sample.
