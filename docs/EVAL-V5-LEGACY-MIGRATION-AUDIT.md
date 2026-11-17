# Legacy v4.1 migration audit

The 35 legacy test cases can support a broader **controlled requested-field benchmark** after a new schema, scorer, evidence-capture preflight, and fresh model run. They cannot be safely rescored as trustworthy natural-incident accuracy merely by replacing the arithmetic function. The eight PostgreSQL views cover only two mechanisms; the legacy set adds breadth but has materially different source quality.

This audit did not read current v5 answers or Haiku verdicts, run models, or change frozen datasets/scorers. The only accompanying artifact is the proposed additive `eval/v5/legacy-migration/field-contracts.json`. It preserves every original gold object, value, and tolerance. Its metadata and proposed unit definitions are not an approved scorer.

## Exact inventory

Source: `eval/v4/dataset.json`, revision 4.1, SHA256 `22b4fd313b699b844c6b16b1378a22753ddcf2149ec880ca5c92e4b1be71ba1f`. The validation archive has the same hash and 40 checks. The source has 40 cases: 5 development and **35 test**. Only the 35 test cases enter this migration.

| Test-set property | Count |
| --- | ---: |
| Cases / named families | 35 / 28 |
| Alert / question cases | 17 / 18 |
| Cases containing numeric fields | 23 |
| Requested fields, with matching gold keys | 62 |
| Numeric JSON gold values | 35 |
| Known categorical gold values | 22 |
| Explicit `unknown` gold values | 5 |
| Numeric fields with PromQL validation | 34 |
| Numeric fields with a log substring instead | 1 |
| Fields with necessary categorical log-marker checks | 8 |
| Fields explicitly requiring both evidence targets | 2 |

The five unknown fields are backup cause, OOM victim, Jellyfin encoding, queue state, and whether an unavailable inventory proves zero containers. Two additional known categorical values are epistemic `no`: firewall blocking is not proved, and missing indexes are not proved. These must not become positive assertions that a firewall or index problem is absent.

All 35 numeric fields have a tolerance: 8 exact, 17 with absolute 0.1, and 10 with absolute 0.01. **No gold field has a machine-readable unit, schema binding, quantity identifier, or requested-window contract.** Units and windows are expressed in question text and/or validation expressions. There are no requested-field/gold-key mismatches.

## Units and proposed typing

| Requested quantity | Fields | Proposed unit/type | Existing dimensional support |
| --- | ---: | --- | --- |
| Utilization/throttling/busy ratios | 9 | `%` | Yes |
| Decimal storage/RSS/available memory | 4 | `GB` | Yes |
| GPU memory | 2 | `MiB` | Yes |
| Disk write rate | 2 | `MB/s` | Yes |
| Clock offsets / query duration | 3 | `s` | Yes |
| Failure increase / OOM increase / current connections | 3 | Event/connection `count` | Yes; event identity and interval remain separate |
| Backup age / certificate remaining lifetime | 3 | Proposed `day`, exactly 86400 seconds | No |
| GPU temperature | 1 | Proposed `°C`, Celsius only | No |
| CPU use | 1 | Proposed `core`, fractional core equivalents | No |
| Probe/reload/synchronization indicators | 5 | Typed categorical numeric symbol | Do not convert dimensions |
| Exit code / HTTP status | 2 | Typed categorical numeric symbol | Do not convert dimensions |

Thus **23/35** source numeric fields use dimensions already recognized by the original numeric contract. Five more need deliberate day/Celsius/core support. Seven are numeric symbols and should use typed categorical comparisons, not `count` or unit conversion. The migration sidecar consequently contains **28 numeric quantities + 7 numeric symbols + 22 categorical fields + 5 unknown fields = 62**.

The sidecar derives units from the exact requested quantities, never by repairing a model answer's unit label. For example, `write_mbps` is an ambiguous alias in isolation, but its question explicitly requests decimal **MB/s**, not megabits/s. Missing answer units still fail closed unless the answering agent was explicitly given a binding for that JSON field. Celsius must not silently become Kelvin, cores must not silently become CPU percent, and elapsed/remaining days are durations evaluated at the fixed clock rather than lookback counts.

## Confirmed defects and limits

1. **The old scorer proves only related-source access.** `score_harness_comparison.py` accepts a matching JSON fact plus an observation whose source/query mentions an evidence target. It does not establish the right labels, value, transformation, interval, or causal relationship. `container_memory_rss` has two series in the memory cases; a query for the wrong container could satisfy the old source-name test. The new sidecar retains expression/label context and requires a separate association check against the delivered observation.

2. **Old arithmetic delegates interpretation to the extractor or ignores units.** The old exact scorer compares floats in `facts` to unlabelled gold magnitudes. The old Haiku review permits the model to emit a normalized number, followed by float/tolerance comparison. Neither deterministically verifies that its number follows from the quoted answer with the original unit intact. A verbatim span, deterministic unit normalization, and separate semantic association are required.

3. **There is a documented gold correction, not a new discovered value correction.** The original Jellyfin encoding gold `software` lacked encoder/acceleration evidence. Published v4.1 errata changed it to `unknown`; this audit preserves that correction. The old archived main score excluded that field, whereas a prospective revised run can explicitly include the corrected field. Those denominators must not be conflated. The current validation hash matches the revised dataset. No additional wrong numeric gold value was established by this read-only audit; the archived validation supports arithmetic consistency, not comprehensive independent semantic correctness.

4. **Observation precision can be coarser than the gold tolerance.** GPU memory gold is 23859.2 MiB with tolerance 0.1, while the hardware summary formats MiB with zero decimal places. A faithfully repeated `23859 MiB` is 0.2 MiB away. The raw PromQL query can expose the precise value, but its existence does not make an unseen value grounded. Predeclare the treatment of a correctly rounded delivered observation: report precision-limited/ungradable or require a more precise reached observation. Do not widen tolerances after seeing answers or borrow hidden raw data.

5. **A field score is not full question completion or an ultimate-cause score.** Some questions ask about growth or whether high VRAM proves an inference failure; their stored fields cover magnitudes, not every prose obligation. Report 62-field accuracy separately from whole-answer completion and unsupported claims. Additional obligations must be explicit before the run, not hidden requirements introduced while judging. `running` does not mean healthy; `not_configured` is not a health pass. An untagged image reference identifies the captured reference, not a known release version.

6. **Archived traces cannot be upgraded into exact delivered observations after the fact.** Fresh model runs must use the fixed delivery recorder, including cache deliveries, the same tool schemas and terminal policy, and no raw-response substitution. In particular, range minima/maxima can be absent from three-sample raw compaction and raw responses may contain series omitted from tool output. Both old recording defects require fresh traces, not invented reconstruction.

7. **The existing v5 scoring pipeline is deliberately scoped to eight cases.** It enforces 48 answers and the specific two-family protocol. A 35-case, two-arm, three-repeat migration produces 210 answers and 420 repeated semantic judgments. The API helper's 240-attempt campaign cap would stop that plan even if dollar spend remained below $2. A new preregistered scorer/attempt policy and explicitly registered cumulative budget are required. Do not bypass the cap by silently splitting output directories, or modify the active comparison's frozen registry/code.

The separate measurement reviewer has also found compound-unit and invalid-JSON parser defects beyond numeric v1.1 and is drafting v1.2 separately. This audit does not certify that draft. Its API currently remains root-key binding only, without day/Celsius/core units or nested JSON pointers.

## Concrete sidecar and migration plan

`eval/v5/legacy-migration/field-contracts.json` has exactly one contract per `(case_id, key)`. It includes the untouched original gold object; exact requested question; source tier; proposed JSON binding and unit; fixed observation time, rate/increase lookback or referenced log-event offsets; validation expression/log substring; relevant metric labels; and separate semantic/evidence policy. For log questions that specify no lookback, the sidecar explicitly leaves requested lookback null rather than treating a tool default as a user requirement.

1. **Freeze a prospective request schema.** Give both arms the same `facts` keys, explicit units/types, and original questions. Bind `/facts/available_gb` to GB, for example, before asking for the answer. These additive schema disclosures change the prospective experiment and must be named as such; they do not justify retrospective interpretation of old arbitrary unitless values.

2. **Implement a strict extraction adapter and finish the numeric contract separately.** Parse the entire candidate JSON with duplicate-key and nonfinite-constant rejection. Verify the enclosing `/facts` path, retain source offsets, and select the exact verbatim facts-object span; then call the existing root-key binding API. A `json_pointer` in this sidecar is a proposed external binding, not an API feature that already exists. Reject conflicting candidate objects or values. For prose, select a verbatim number/unit span without rewriting it. Preserve quoted labels and absolute tolerances. Add the three proposed unit families only with independent synthetic tests and a separate version freeze.

3. **Keep correctness, association, and grounding separate.** Numeric correctness comes only from code. Semantic judging decides whether the quoted quantity answers the requested field for the requested entity/window and is supported by the exact delivered observation. Categorical numeric symbols retain exact numeric type, reject booleans, and may accept a separately verified quoted semantic equivalent without dimensional conversion. Unknown fields require explicit, evidence-consistent uncertainty, not omission. Deterministic numeric failures cannot be repaired by semantic judgments, and numeric passes cannot prove provenance.

4. **Validate without answer-driven gold tuning.** Recheck the unchanged 34 PromQL expressions and one log value through the current fixture/renderer, then audit categorical evidence, both port-mapping sources, current-window versus lookback distinctions, label selection, rounding, and hidden host-only evidence. Add independent controls for these mechanisms before model collection. Version any newly established gold defect in explicit errata; do not silently alter this sidecar's values/tolerances.

5. **Run a new registered broad comparison.** Parameterize the expected case/arm/repetition grid from a frozen protocol. Retain every error/missing result in the denominator. Report field micro accuracy over 62 fields and case macro accuracy over 35 cases separately, with family/source-tier breakdowns and whole-answer unsupported-claim/completion measures. Repetitions and alert/question variants are not independent incidents. Use the shared cumulative ledger and explicitly approved call-count policy; no paid calls have been made for this audit.

A practical effort estimate is approximately 1–2 focused engineering days for the adapter, unit/schema support, and generalized frozen-grid scorer, followed by roughly 0.5–1 day of independent fixture/semantic-control review. Runtime and paid validation are additional. A 210-answer run allows up to 5.25 hours of investigation deadlines alone (210 × 90 seconds), before fixture/bootstrap/review overhead; this is an upper-bound planning calculation, not a measured latency forecast.

## Source-quality tiers and naming

| Provenance tier | Test cases | Defensible description |
| --- | ---: | --- |
| Manual derived controlled fixture | 30 | Authored observations based on operational concepts; not published incident replays |
| Published fault-type adaptation | 2 | Kubernetes target-port fault concept adapted to Docker, including its matched control; not original benchmark-score comparability |
| Sanitized live snapshot | 3 | Captured inventory questions, not failure incidents; `up` is a fixture anchor |
| Natural incident replay with incident identity | 0 | No such claim supported |

All 35 source `incident_id` values are null. Generic source links and operational-rule validation do not turn synthetic examples into real incident histories. Keep these tiers separate from the PostgreSQL reproduced-failure tier. Name a future result **“35-case legacy controlled requested-field benchmark”**, with the source mix and limitations attached, rather than “natural home-server incident accuracy.”
