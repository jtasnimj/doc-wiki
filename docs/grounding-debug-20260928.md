# Grounding diagnosis — 2026-09-28

The grounding failure is reproducible and remains unresolved. No experimental
generation or retrieval change has been adopted by the running application.
The approved eight-case paid diagnostic rejected the proposed evidence-first
generation schema: it still lost defining question qualifiers and introduced
four execution errors. A separately approved twelve-case answer-review diagnostic
also failed the core workbook patterns and introduced three execution errors.
Valid citations and genuine quotations do not establish that the cited text
answers the complete question.

This investigation follows the [19-case paid retest](live-retest-20260928.md).
The workbook cases are development data. Gold/reference answers were used only
for review, never included in generation, embeddings or ranking inputs.

## Reproduction and cause separation

The offline replay rebuilds an isolated LlamaIndex/Chroma index from the saved
723 document vectors and uses saved question vectors. It makes no provider calls
and reads the application cache through SQLite in read-only mode. Running it
twice reproduced the same missing audience evidence for the continuity question:

```text
.venv/bin/python evaluation/runs/grounding-debug/replay_retrieval.py
required_evidence_coverage: [true, false]
pages: [24, 82, 54, 78, 82, 82]
AssertionError: Continuity plans were retrieved, but documented audience/accessibility was omitted.
```

This is intentionally a failing diagnostic, not a passing regression test. The
local script requires the ignored supplied-source artifacts and saved vectors.
It must not be treated as a portable test that works after a fresh clone.

The evidence distinguishes these failures:

| Failure | Observation | Consequence |
|---|---|---|
| Question scope is lost during generation | The FDA qualifier disappears from the prototype's requirement list; wireless scope disappears from its monitoring subpart | Neither valid JSON nor deriving status from that list can recover an omitted qualifier |
| Criteria become implementation claims | Case 2 cites the broad audit criterion as the actual installation control; table columns are generically numbered | Source-ID allowlisting cannot distinguish a requirement from its implementation; table role/context is a separate representation problem |
| Complementary evidence ranks too low | All 22 reviewed positive evidence groups are extracted, but only 14 are in the top six; necessary groups first appear as low as ranks 48, 61 and 71 | Generation cannot reliably fill these gaps without retrieving more appropriate context |
| Citation validity is mistaken for support | Replaying unsupported captured answers through the current validator accepts valid source IDs | The validator establishes provenance and response shape, not semantic entailment |
| Cross-field model decisions are inconsistent | Case 18 originally supplied partial without citations; the prototype emits missing decisions with quotes and empty statements | Returning an execution error is correct; weakening validation would hide the failure |

These findings do not imply a need to switch models, add agents or hardcode
question-specific handling. The current model, public response and source
isolation remain unchanged.

## Retrieval experiments

Saved vectors and candidates allow ranking experiments without new embeddings.
Gold evidence locations were used after ranking to score results, never as
features or boosts. All methods returned at most six passages. The metric is
coverage of 22 reviewed evidence groups across eight positive/partial cases;
it is not answer accuracy or a held-out score.

| Experimental selection | Evidence groups | Fully covered cases | Decision |
|---|---:|---:|---|
| Dense baseline | 14/22 | 1/8 | Keep as current behavior |
| Exact-text deduplication, candidate pools 12–96 | 14/22 | 1/8 | No measured benefit |
| Diversity selection, dense weights 0.5–0.9, pools 12–96 | At most 14/22 | No overall coverage gain | Does not fix the reproduced miss |
| BM25 token matching alone | 9/22 | 0/8 | Reject |
| Reciprocal-rank fusion, dense weight 0.75 | 15/22 | 2/8 | Small net gain; loses one access-control group; insufficient justification to ship |
| Reciprocal-rank fusion, dense weights 0.5 / 0.25 | 12/22 / 10/22 | 1/8 / 0/8 | Reject |

The lexical probe used lowercase alphanumeric tokens, BM25 parameters 1.5/0.75
and reciprocal-rank constant 60. It is a local diagnostic implementation,
not a new application dependency. No reranker, hybrid retriever, query rewriting
or cross-page table reconstruction was added. A small synthetic duplicate-only
failure was also reproduced, but fixing that simplified example would not fix
the actual saved case; it is not evidence for a production deduplication change.

## Approved eight-case generation diagnostic

The experiment reused the exact saved top-six passages for workbook cases
2, 4, 5, 13, 15, 18 and 19, plus an authored explicit-negative control. It made
eight sequential `gpt-4o-mini` calls and no embedding calls. It tested a separate
schema requiring quotations, supported/missing/conflicting assessments and
statements, with the application deriving status and citations. The running
application was not changed.

| Case | Target | Prototype outcome | Review |
|---|---|---|---|
| 2: installation controls | not_found | answered | Quotes the audit criterion as proof of implementation; unsupported conclusion persists |
| 4: key purpose and confidentiality | partial | error | Rewrites quotation punctuation, failing exact-source validation; the raw assessment also treats generic key management as sufficient for the unique-purpose requirement |
| 5: environmental controls | partial | partial | Removes the blanket Yes and identifies some gaps, but still labels the temperature/humidity/testing requirement supported by generic environmental responsibilities and omits the carved-out audit limitation |
| 13: regulated software QA | not_found | answered | Drops the regulatory qualifier and answers a broader QA question |
| 15: wireless monitoring | not_found | partial | Treats generic intrusion detection as an independently answered wireless-policy subpart |
| 18: device inventory scope | not_found | error | Missing decision carries quotations and an empty statement, violating the schema's semantic constraints |
| 19: formal access process | answered | error | Regresses a supported control; missing decision has quotations and an empty statement, and a quote is rewritten |
| Explicit negative | answered with No | error | Marks a directly supported negative as missing, while retaining its quote |

Four results compiled and four failed validation. Only case 5 matched its target
status, and status agreement does not make its answer complete or fully grounded.
The fifteen offline prototype tests passed, demonstrating compiler contracts
only; this paid run demonstrates why those tests cannot prove model quality.

Reported usage was **15,567 input tokens and 1,485 output tokens**, with zero
cached input tokens and no retries. Estimated cost was **$0.003226**, using the
published [gpt-4o-mini rates](https://developers.openai.com/api/docs/models/gpt-4o-mini).
This is an estimate from token usage, not an invoice. The approved eight calls
are complete and must not be rerun under that authorization.

## Approved twelve-case answer-review diagnostic

The second experiment reviewed a draft against the full original question and
the same retrieved evidence, using `gpt-4o-mini` and the existing `ModelAnswer`
schema. It tested whether reviewing a concrete claim is more reliable than
generating an evidence plan and answer together. No extra review pass was added
to the application.

The run contained seven captured workbook drafts and five authored
controls: explicit negative, supported positive, explicit non-applicability,
weakly related evidence, and contradictory evidence. It made twelve generation
calls, no embeddings, and no changes to the interactive application. References
are excluded by an explicit input allowlist. Three offline tests verify reference
isolation, separate-approval gating, and one-time execution through the actual
response validator; they do not evaluate semantic quality.

The disclosed configured-limit estimate was **$0.044896**, including one transient retry
for every call. It uses a conservative UTF-8-byte allowance for input tokens plus
request overhead and 1,200 maximum output tokens per case; expected usage is
under $0.01. The user approved these twelve calls separately, as required by the
implementation plan.

| Case | Validated outcome | Review |
|---|---|---|
| 2: installation controls | answered | Repeats the unsupported installation conclusion and adds monthly OS patching as further apparent support |
| 4: key purpose and confidentiality | answered | Repeats the unsupported unique-purpose assertion |
| 5: environmental controls | error | Returns commentary about correcting the draft rather than a direct answer; partial plus related information violates the existing contract |
| 13: regulated software QA | answered | Retains the unsupported FDA assertion and adds ordinary peer review as apparent support |
| 15: wireless monitoring | error | Retains the wireless-policy inference; partial plus related information fails validation |
| 18: device inventory scope | partial | Adds valid citations, but still treats broad inventory coverage as a partial answer to an unsupported scoped claim |
| 19: formal access process | answered | Preserves the supported requested process |
| Explicit negative | answered | Correctly answers No with the explicit negative evidence |
| Supported positive | answered | Preserves the supported approval/provisioning answer |
| Explicit non-applicability | answered | Correctly preserves the documented non-applicability |
| Weakly related evidence | error | Converts missing physical-protection evidence into No; answered without citations fails validation |
| Contradiction | partial | Reports both retention periods without inventing a resolution |

Nine results passed structural validation and three did not. Source review finds
only one of the seven workbook outputs acceptable for the requested question;
four of the five authored controls pass. This is an assistant review of selected
development cases, not a held-out accuracy estimate. The rejected outputs show
that this review pass does not provide an adequate semantic guard. The results
are consistent with draft anchoring, but this experiment alone does not establish
anchoring as the sole cause.

Reported usage was **17,931 input tokens and 1,444 output tokens**, with no cached
input tokens or retries. Estimated cost was **$0.003556**. Both approved runs
together made **20 generation calls**, zero embedding calls, and cost an
estimated **$0.006782**. Both authorizations are consumed; the runners prevent
automatic reruns.

## Decision and remaining work

Neither prototype meets the promotion gate: preserve defining qualifiers,
do not turn related facts into answers, retain supported positive/negative/N/A
answers, report contradictions, and introduce no new execution errors. Keep both
out of the running app. Do not normalize unsupported conclusions into not_found
through keyword rules, relax citation validation, or silently change the model.

Before another paid experiment, the next implementation design should address
the representation boundary: preserve question qualifications independently of
evidence selection, preserve recoverable table roles and section context, and
retrieve missing subpart evidence without source-specific boosts. These are
requirements for a new design, not fixes established by this investigation.
The single-pass schema, duplicate removal, basic lexical fusion and same-model
draft review tested here do not resolve the failures. Further prompt-only paid
iteration is not justified by these results.

Any future candidate needs a deterministic structural regression suite and
source-reviewed semantic evaluation, including these negative, positive,
non-applicability, weak-evidence and contradiction controls. A successful
selected-case diagnostic would still need a separately approved broader
evaluation before claiming improvement. The original held-out suite remains
unchanged.

Verification after the investigation: Ruff lint and formatting passed, mypy
passed for all 17 source modules, and all **111 offline application tests** passed.
The experimental suites passed **15 compiler tests** and **3 review-runner tests**.
These are contract/plumbing results; the live semantic failures above take
precedence when deciding whether to ship a prototype.

## Local artifacts

Full source-containing material remains ignored in
`evaluation/runs/grounding-debug/`:

- `replay_retrieval.py`, `probe_candidates.py`, `dense-candidates.json`: actual
  retrieval replay and full ranked candidates.
- `compare_selection.py`, `probe_lexical.py`, `lexical-probe-results.json`:
  offline selection experiments.
- `evidence_plan.py`, `test_evidence_plan.py`, `run_evidence_probe.py`:
  rejected generation prototype and guarded runner.
- `evidence-probe-inputs.json`, `evidence-probe-results.json`: exact paid input,
  output, validation failures, latency, hashes and reported usage.
- `audit_probe.py`, `audit-probe-inputs.json`, `audit-probe-results.json`,
  `test_audit_probe.py`: completed independent-review experiment and its guarded
  runner, inputs, results and offline isolation tests.

No supplied-file redistribution, cache reset, Docker cleanup, new paid
embedding, runtime prompt change or retrieval tuning was performed. The original
retrieval reproduction is still red; this report records a diagnosis and rejected
fixes, not a claim that grounding is fixed.
