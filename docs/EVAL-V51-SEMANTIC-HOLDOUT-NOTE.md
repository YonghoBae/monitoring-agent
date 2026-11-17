# V5.1 semantic judge holdout authorship note

[semantic-holdout-v51.json](../eval/v5/semantic-holdout-v51.json) contains 20 new synthetic controls, authored and frozen before the reviewer inspected any new v5.1 judge prompt or implementation. Its current SHA256 is `1bf86134a826838554c805f2fecf36bcca41851fbf2d0802851bb4c7412fa2c7`. No model or paid API calls were made while creating these controls.

The original freeze had SHA256 `78cf8869bddaa49f66a55d3082e13fe2fcbef262c0eb9774eba4e6cf2a76568d`. Before the new prompt was implemented or the prompt author saw labels, the contract was clarified to add `answer_correct` explicitly. All 20 payloads remain unchanged. This pre-prompt schema refinement and the previous identity are preserved in the holdout metadata; it is not a revision informed by model judgments.

The motivation was a distinction exposed by the prior blinded review: answering every enumerated reference field need not answer the entire natural-language question. The new instrument therefore separates `complete_answer` from factual correctness and unsupported claims. These controls use new mini-observations across several operational contexts rather than reproducing the collected benchmark answers.

`complete_answer` means that every requested result clause in the question receives a substantive response, including clauses absent from `reference.required_findings`. Explicit unknown or not-run status can complete a clause when observations justify it. A concise answer can be complete. Silence is not an explicit unknown. Completeness measures coverage: a definite but unsupported answer may address every clause while still failing the overall verdict.

`answer_correct` means every requested result clause is correctly answered and grounded, including clauses omitted from the reference enumeration. An omitted clause makes this label false. An attempted wrong answer can be complete but incorrect. Explicit uncertainty is correct only when the reached observations do not establish the requested result. An unrelated unsupported extra assertion can leave the requested answers correct while still preventing an overall pass.

`pass` requires `answer_correct`, correct and grounded required reference findings, no unsupported factual assertions, and a complete answer. `unsupported_claims` remains independently visible. `answer_status` distinguishes substantive definite answers, wholly explicit uncertainty, and no substantive answer; an answer combining a definite primary result with an unknown secondary result uses `answered`.

The controls cover omitted secondary-operation results, legitimate concise answers, unavailable observations, immediate file-access diagnostics versus unsupported ownership explanations, filtered catalog scope, clearly qualified hypotheses, untrusted instructions in logs, empty versus positive observations, and missing historical comparisons. Numerical arithmetic and unit conversion are outside their scope.

Each case retains the existing judge payload shape: question, answer, judge-only reference and reached observations with IDs. Expected labels, case identifiers and categories are outside the payload. Only the payload should reach the judge. The reference cannot provide observation support that the evaluated agent did not reach.

The author did not inspect `semantic_judge_v51.py` or any future replacement prompt. The holdout's labels were not shared in the handoff message. Since the repository is shared, this is a documented separation procedure rather than a technical secrecy guarantee. Freeze the new judge prompt, parser and development controls before revealing or evaluating this holdout. Preserve failed attempts; a prompt revision informed by holdout failures needs fresh independently authored validation material.

This is independent authorship by a separate AI reviewer, not independent human validation or proof of freedom from shared AI biases. The frozen older questions, collected answers, gold and harness remain unchanged. Passing these controls would validate only the tested behaviors, not a population error rate or general troubleshooting capability.
