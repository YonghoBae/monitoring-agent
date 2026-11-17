# v5 scoped comparison protocol — frozen before model comparison

The target is trustworthy, auditable measurements on eight observation views from TWO PostgreSQL failure mechanisms. It is not overall home-server accuracy and does not replace the old 35-case score with an allegedly representative eight-case score.

## Data and experimental unit

Two publicly documented mechanisms are reproduced in isolated containers: old pg_dump versus a newer server, and unreadable initial SQL. Each supplies normal, failed, fresh recovery, and detail-withheld views. All observations originate in captured operations; aliases, collection wrappers and withheld-detail controls are adaptations. The original GitLab outage and issue #722 are not replayed in full. PostgreSQL versions/distributions differ from source incidents. Recovery for initial SQL uses a fresh data directory.

Eight views are correlated within two families. Repeated executions are not new incidents. No population confidence interval or significance claim treating 24 executions as independent incidents is permitted. Report family results, per-case repeats, and observed paired differences. Do not force a general winner.

## Frozen comparison

- Arms: actual Pi 1.5.2 `pi_plus` and actual application `FocusedInvestigator` `compact_plus`.
- Same Qwen3.5 9B model identity from Ollama, same system prompt, question, tool definitions and worlds, temperature 0, per-completion output cap 1536, 12 uncached tool invocations, 90-second investigation deadline. Total generated token budgets are not claimed equal.
- Three repetitions of every case/arm: 48 answers total. Serial model requests and explicit counterbalancing using within-family case ordinal plus repetition parity. Each arm is first in 12 of 24 pairs, 6 of 12 pairs per family, and 4 of 8 pairs per repetition. No prompt or gold tuning between cases/repeats.
- Pi process bootstrap is inside its 90-second deadline. Common terminal execution policy retains the bounded observation summary. Exact delivered tool envelopes, including cached deliveries, are the primary semantic evidence; raw service responses are separate diagnostics.
- Only question, answer_fields, fixed observation clock and reached tool outputs enter agent input. IDs, family, phase, gold, source URLs and intervention metadata do not.
- Production/native earlier scores remain historical. This is the controlled enhanced-tool comparison, not a new claim about deployed production performance.

## Scoring and validation

The only required scored findings are recorded operation status and directly observable cause (or explicit inability to determine cause). Optional row-count facts are not hidden completeness requirements. No blanket system-health or production-recovery claim is justified.

Semantic judge is Haiku 5.5 through official Anthropic Messages API, arm-blinded and prior-score-blinded. An independent AI reviewer authored and froze 20 controls before the judge implementation. Sixty judgments (three repeats) all matched expected pass/unsupported labels. This is limited calibration evidence, not proof of universal judge accuracy. A stricter structural validator was applied offline to all 60 frozen responses without changing their semantic prompt/decisions; all remained valid.

Each comparison answer receives TWO independently repeated semantic judgments. Report both pass rates; a stable pass requires both valid passes. Disagreements or invalid outputs remain unresolved and are counted as non-passing in conservative results, never repaired into semantic agreement. Empty answers receive deterministic fail/no-claim. Runner errors remain in the denominator. Independent AI review samples outputs and reviews disagreements before publication; it is not human validation.

Numbers/units use the separately versioned Decimal contract, not LLM arithmetic. v1.0 defects and v1.1 corrections are retained. This v5 comparison scores status/cause only; numeric parser validation is reported separately, and does not retroactively certify the v4 numeric score.

All source, gold, prompt, runner, model metadata and raw response artifacts receive hashes. Paid calls are centralized, recorded before/after each request, and stop on uncertain outcomes. Total campaign budget including prior $0.0386223 is $2; price estimates are token-accounted, not an invoice. No operational deployment or production fault injection.

## Order amendment before answer inspection or scoring

The first comparison attempt used separately seeded Java Random shuffles. An order-only audit found all 24 planned pairs would put Pi first because adjacent seeds/case IDs produced correlated first bits. After 14 answers were collected, that attempt was stopped without inspecting answer content or calculating any score. All original inputs, unchanged hash verification, logs and 14 answers remain in `eval/v5/comparison-1/`; they are excluded from scoring. No paid judge calls were made for that attempt.

The balanced schedule above replaces the failed randomization in a new frozen `comparison-2` campaign. Questions, gold, model, tools and judge semantics are unchanged. This amendment is motivated by experimental ordering, not observed performance.
