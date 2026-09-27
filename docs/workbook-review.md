# Workbook baseline and grounded-answer review

One approved run used the exact 19 workbook questions against the SOC 2 PDF, before changing behavior at commit `10caac8`. The workbook was never ingested as evidence. Its `answer` cells are comparison references; comments and confidence were ignored. All 19 inspected cases are development cases. The original 12-development/six-held-out manifest is unchanged.

The local capture is `evaluation/runs/workbook-baseline.json`. It contains actual answers, ordered retrieved passages, citations, warnings, per-question retrieval/generation latency, models, configuration and reported usage. The full 19-row report, including each reference answer and actual answer, is `evaluation/runs/workbook-review.html`, with a JSON equivalent. These files contain supplied material and remain ignored. The committed `evaluation/workbook_cases.json` contains authored source judgments, evidence requirements, source/workbook hashes, diagnoses and proposed fixes. `python -m docwiki.workbook_review` rebuilds the report offline and rejects a mismatched source, workbook, question or baseline commit.

## Observed baseline

| Observation | Result |
|---|---|
| HTTP / completion | 200; all 19 completed; no execution errors |
| Actual statuses | 11 answered, 1 partial, 7 not_found |
| Source-supported targets | 4 answered, 4 partial, 11 not_found |
| Status agreement | 11/19; **not factual accuracy** |
| Evidence hit@6 | 8/8 cases needing positive evidence retrieved at least one required group |
| All required groups at6 | 1/8; 14/22 individual evidence groups retrieved |
| Structural citation validity | 19/19, including valid uncited abstentions; **not semantic support** |
| Correct abstention status | 7/11 target not_found cases; no false abstention among eight positive/partial targets |
| End-to-end request latency | 19,774 ms, including fresh ingestion |
| Reported embedding tokens | 57,459 |
| Reported generation tokens | 29,370 input; 1,963 output |
| Estimated successful-call cost | $0.006732, using the disclosed text-model rates |
| Post-change live evaluation | Not run; separately approved paid retest required |

The 22 evidence groups pair reviewed phrases with acceptable PDF pages. All 22 are present in the stored text/table extraction for this source; retrieval misses are not extraction loss. They cover the positive portions of the four answered and four partial targets. Optional related facts for unsupported questions do not enter this denominator. Some groups test completeness of the richer target (for example access removal), beyond the narrower baseline answer. This is a targeted coverage check, not a universal retrieval-quality score. Full evidence for case 4 was retrieved, yet generation still overclaimed unique-purpose provisioning.

The run used `gpt-4o-mini`, `text-embedding-3-small` at 1,536 dimensions, 700-token narrative chunks/100 overlap, top-six dense retrieval, 6,000 evidence tokens, four provider calls concurrently and vision disabled. Cost uses the previously reviewed $0.02/M embedding and $0.15/M input/$0.60/M output generation rates; reported usage is not a statement of account balance or a billing invoice.

## Case decisions

The full local report includes verbatim references/results and expandable ranked passages. This distributable table summarizes the source-reviewed decisions without reproducing the supplied answers.

| Case | Topic | Baseline → target | Diagnosis and generic remedy |
|---|---|---|---|
| 1 | Data-centre geography | not_found → not_found | Explain missing geography/residency; provider identity may be separately cited. |
| 2 | Unauthorized installation | answered → not_found | A SOC criterion and antimalware do not establish installation restrictions. Distinguish requirement from implementation. |
| 3 | Continuity-policy audience | answered → answered | Plan existence was retrieved; audience evidence was missed. Require both before claiming availability. |
| 4 | Private-key purpose | answered → partial | Lifecycle/confidentiality evidence does not prove unique purpose. Address independent subparts. |
| 5 | Environmental controls | answered → partial | Preserve expected supplier responsibilities and carved-out scope. Missing adjacent scope context warrants a retrieval experiment. |
| 6 | Secure protocols | answered → answered | Generic encryption is insufficient for protocol/version details; retrieve complementary protocol passages. |
| 7 | Infrastructure lifecycle | answered → partial | General policies do not prove every virtualization-specific lifecycle step. Preserve system scope. |
| 8 | Annual review/update | answered → partial | Review is not mandatory change; as-needed policy-update evidence was missed. Keep citation IDs out of prose. |
| 9 | Transport containers | not_found → not_found | Explain missing physical protection; omit lexical matches about encrypted transport. |
| 10 | Non-standard ports | not_found → not_found | Explain missing port assignments; approved ports are not evidence of particular numbers. |
| 11 | Incident reporting | answered → answered | Reporting-mechanism evidence was missed among repeated plan rows. Support reporting and response separately. |
| 12 | Sanctions officer | not_found → not_found | An undisclosed role does not establish No; omit unrelated security roles. |
| 13 | FDA-specific QA | answered → not_found | Generic QA was promoted into regulated scope. Require that scope or explicit non-applicability. |
| 14 | Simultaneous wired/wireless | not_found → not_found | Remote working cannot establish this rule or N/A. |
| 15 | Rogue wireless scans | answered → not_found | Generic IDS cannot establish wireless scope or a scanning frequency. |
| 16 | Signature-update deadline | not_found → not_found | Separate deployed antimalware from a numeric signature-update commitment and OS patching. |
| 17 | Failed-login lockout | not_found → not_found | Explain missing behavior/threshold. MFA and idle logout cannot imply lockout; do not cite unretrieved MFA facts. |
| 18 | IoT inventory | partial → not_found | General inventory does not answer a single IoT-scoped claim. Move inventory into related information. |
| 19 | Role-access process | answered → answered | Broadly supported. Preserve process wording, avoid an invented product; removal checklist was outside top six. |

The workbook contains ten unsupported reference claims, four needing qualification, four broadly supported affirmative answers and one supported abstention. A mismatch with an unsupported reference is desirable. Even agreement on status can conceal an unsupported factual claim, as in cases 3, 6 and 11.

## Implemented changes and remaining experiments

The shared prompt now separates requested subparts, population/system scope, numeric commitments, review/update timing, supplier expectations and audit results. Specific abstention explanations survive server validation. Optional related facts have their own bounded schema and server-derived citations; missing/foreign IDs are errors. The UI labels related facts explicitly and exports the unchanged response. No company-specific branches, question matching, page boosts or reference lookup were added to runtime generation.

Dense retrieval is unchanged. The capture shows repeated incident/continuity rows crowding out complementary evidence, a standalone heading, and omitted adjacent scope context. A future approved development experiment should compare a larger dense candidate set with generic duplicate removal, then inspect whether preserving section/table context fixes supplier qualifications. Evaluate one change at a time against the captured misses; keep top-six final evidence and citation provenance, and retain only measured improvements. Do not adopt BM25, a reranker, rewriting or stitching on speculation. No query vectors were retained, so the saved text capture alone cannot reproduce a changed dense ranking.

`evaluation/grounding_cases.json` adds 24 authored, paraphrased and counterfactual scenarios. The same lockout question appears with absent, explicit negative and explicit affirmative evidence. Other cases cover explicit N/A, contradictions, injection-shaped text, weak lexical matches and each reviewed scope failure. Offline tests pass authored model outputs through the real multipart/parsing/index/retrieval/validation path; mocked SDK tests cover nested structured output. These are contract regressions and semantic evaluation targets, **not proof that the revised prompt makes the model choose those answers**. Reference-field mutation produces identical provider inputs, and changed references do not change source-based report metrics.

Every row's retest outcome remains explicit: offline contracts verified; post-change live semantic quality unmeasured. The expected gain is better grounding and more useful abstention, not imitation of unsupported reference claims. A later 19-case paid retest and human citation-entailment review must measure that gain before claiming improved accuracy.
