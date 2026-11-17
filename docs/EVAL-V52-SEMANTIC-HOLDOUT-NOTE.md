# V5.2 exhaustive-reference holdout

[semantic-holdout-v52.json](../eval/v5/semantic-holdout-v52.json) contains 20 independently authored synthetic controls for the unchanged original semantic judge. Its frozen SHA256 is `ab28ec057dbc83586efc21b0631e83c36f14bf2f5dcaa23b130a2d6e330dae5b`. No model or paid API calls were made to author this suite. The holdout was frozen before the parent inspected its expected labels.

Every requested result clause is explicitly represented in `reference.required_findings`. An outside-payload `clause_coverage` map links a verbatim excerpt of the question to its required finding key. This makes the question-to-reference coverage contract reviewable directly rather than asking the judge to infer an extra completeness checklist. Structural checks verify that every coverage excerpt occurs in the question and that coverage keys, reference keys and expected finding keys match.

The verdict retains the original dimensions: `pass`, `unsupported_claims`, `answer_status` and the per-finding result map. A finding is satisfied only if the answer substantively supplies a correct, grounded result. Omitting a secondary result makes its finding false. Correct explicit uncertainty can satisfy a finding when the reached observation cannot establish the requested result. No global `answer_correct` or `complete_answer` labels are introduced.

The controls include three- and four-finding questions, concise complete responses, missing secondary outcomes, known process failure with unknown startup phase, bounded permission-error explanations, filtered catalog scope, empty observations, historical uncertainty, untrusted log instructions and qualified causal hypotheses. Count-query controls report an observed literal result in ordinary words; they require no arithmetic, unit conversion or tolerance judgment.

Only each case's `payload` should reach the judge. Expected labels, identifiers, categories and coverage maps remain outside it. References cannot substitute for reached observations. The expected labels were not disclosed in the freeze handoff message.

This suite does not relabel the earlier failed expanded-diagnostic validation as a success. Those attempts and the earlier holdout identities remain distinct. The proposed acceptance gate requires all predeclared pass, unsupported-claim and per-finding outcomes to match across all repetitions; it must not be relaxed after seeing results. A failed gate remains a failed validation attempt, even if a subset of labels agrees.

The author is a separate AI reviewer, not an independent human auditor, and shared model biases remain possible. Passing this synthetic suite would establish only the tested judge behavior. Applying the strategy to real answers additionally requires an independently reviewable, observation-grounded coverage map for every actual question. Existing collected answers, questions, harness inputs and gold are unchanged by this holdout.
