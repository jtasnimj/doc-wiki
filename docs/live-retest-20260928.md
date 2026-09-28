# Paid workbook retest — 2026-09-28

The user approved a full paid pass of the 19 workbook questions after the grounded-answer changes. The run tested commit `ec96e2d` with the same PDF, exact question IDs/wording and configuration as the baseline. It submitted a real multipart request to `/api/qa` through HTTPX's ASGI transport, used a fresh temporary index and the official paid SDK, and left the interactive server's saved indexes untouched. Workbook reference answers stayed outside generation inputs. No application code, model selection or retrieval settings were changed during this test.

**The live result does not demonstrate an improvement in grounding.** Status agreement remains 11/19, and matching status is not factual correctness. Several affirmative answers still infer unsupported scope or controls. One formerly partial result now fails citation validation. Specific abstention wording improved, but the model returned no separately cited related-information sections.

## Results

| Measure | Before | Retest |
|---|---:|---:|
| Cases attempted | 19 | 19 |
| Answered / partial / not_found / error | 11 / 1 / 7 / 0 | 11 / 0 / 7 / 1 |
| Agreement with source-supported target status | 11/19 | 11/19 |
| Correct abstention status | 7/11 | 7/11 |
| Complete required evidence within top six | 1/8 | 1/8 |
| Individual required evidence groups retrieved | 14/22 | 14/22 |
| End-to-end latency, including fresh ingestion | 19.774 s | 19.480 s |

The HTTP response was 200 with `batch_status: partial_failure`, preserving the 18 completed answers alongside one execution error. Source-ID/excerpt/location checks pass for the 18 returned non-error results, but that does not establish support for their claims. All 22 reviewed positive evidence groups survive extraction. Ranked evidence is identical to baseline for 18 questions; case 14 has a small ranking/content change despite unchanged settings. No extraction/retrieval tuning or additional paid repair runs were performed.

The model returned seven specific not-found explanations and zero related sections. Source review separates seven unsupported affirmative conclusions, three affirmative answers missing necessary retrieved/cited evidence, three abstentions with uncited background, five acceptable answers to the requested questions, and one execution error. These are assistant source-review judgments on this development set, not independent human approval or a general model benchmark.

## Each case

| Case | Target | Actual | Reviewed outcome / next action |
|---|---|---|---|
| 1 | not_found | not_found | Geographic gap explained, but provider facts appear in uncited main prose. Separate/cite the related fact or omit it. |
| 2 | not_found | answered | Installation restrictions are inferred from SOC criteria, antimalware and patching. Require evidence for the actual restriction. |
| 3 | answered | answered | Plan existence is cited as proof of stakeholder accessibility. Retrieve and cite audience evidence. |
| 4 | partial | answered | Unique-purpose provisioning is still asserted without evidence despite sufficient lifecycle/confidentiality retrieval. Require independent subpart support. |
| 5 | partial | answered | Supplier responsibilities become implemented/tested temperature/humidity controls. Preserve supplier and audit-scope qualifiers. |
| 6 | answered | answered | Generic encryption is used to claim standardized management/import/export protocols. Retrieve concrete protocol/version passages. |
| 7 | partial | answered | General policies become every requested virtualization lifecycle requirement. Check system scope and each requested subpart. |
| 8 | partial | answered | Annual review is stated, but the update obligation is omitted while answering Yes. Separate review/update requirements. |
| 9 | not_found | not_found | Correct physical-protection abstention includes weak, uncited data-security background. Omit it. |
| 10 | not_found | not_found | Pass: specific missing port information, no invented Yes/No. |
| 11 | answered | answered | Incident procedures do not establish the cited reporting mechanism. Retrieve reporting evidence separately. |
| 12 | not_found | not_found | Pass: missing sanctions role is not converted to No. |
| 13 | not_found | answered | Generic QA is still promoted to FDA-regulated assurance. Require explicit regulated scope. |
| 14 | not_found | not_found | Pass: missing simultaneous-connection rule is not converted to N/A. |
| 15 | not_found | answered | Generic IDS is promoted to wireless-policy monitoring. Preserve the actual control scope. |
| 16 | not_found | not_found | Pass: missing signature-update deadline is stated without inference from OS patches. |
| 17 | not_found | not_found | Correct lockout gap plus uncited broad access-control context. Omit background or cite a directly relevant fact separately. |
| 18 | not_found | error | Model supplied partial with no source IDs. Validator correctly returned invalid_model_output. Improve status/evidence selection; do not weaken citation validation. |
| 19 | answered | answered | Pass for requested formal access process. Richer review/removal detail remains limited by complementary retrieval. |

## Usage and verification

Generation resolved to `gpt-4o-mini-2024-07-18`; embeddings used `text-embedding-3-small`. There were 19 generation calls and 42 embedding calls, with no transient retries. Reported usage: 57,459 embedding tokens, 37,192 generation input tokens (2,048 cached), and 1,988 output tokens. Estimated cost is **$0.007767** with the reported cached-input discount, or **$0.007921** at the standard input rate throughout. Both are under $0.008 and below the disclosed $0.14 conservative estimate. This is an estimate from reported usage, not an invoice or account-balance statement. Rates were rechecked against the official [generation](https://developers.openai.com/api/docs/models/gpt-4o-mini) and [embedding](https://developers.openai.com/api/docs/models/text-embedding-3-small) pages.

Frozen dependency sync, Ruff lint/format, mypy and all 111 offline tests passed. The original 18-case offline evaluation ran with zero skipped cases and unchanged diagnostic metrics. The full Chrome smoke passed with fake providers. A second browser check replayed the captured paid response without further model calls: all 19 ordered cards, the actual error card, and unchanged JSON export passed. The 19-case report rendered correctly. The Docker daemon was initially stopped; after starting the existing Colima VM, the build reached dependency installation but failed while applying the layer with `no space left on device` in containerd storage. Container smoke therefore could not run. No Docker images, volumes or user caches were pruned. The original held-out suite and the 24 synthetic scenarios were covered offline only; no paid held-out or synthetic run occurred.

Full local artifacts remain ignored because they contain supplied reference answers and source excerpts:

- `evaluation/runs/workbook-retest-20260928.json`: exact response, ranked evidence, raw model outputs, provider timings/models, usage and provenance.
- `evaluation/runs/workbook-retest-review-20260928.html` and `.json`: baseline/reference/actual/target comparison and individual source/citation judgments.
- `evaluation/runs/workbook-retest-extraction-20260928.json`: extracted source blocks.
- `evaluation/runs/workbook-retest-query-vectors-20260928.json`: captured query vectors for later offline retrieval diagnosis.
- `evaluation/runs/run_workbook_retest.py`: capture script, guarded against rerunning this completed paid pass.
- `evaluation/runs/review_workbook_retest.py`: offline regeneration of this run's detailed review.

## Next implementation decision

Prompt instructions alone were insufficient in this run. The next generic experiment should require explicit evidence decisions for requested subparts and preserve table roles/section context, then derive the status from supported coverage. A bounded repair for structurally invalid output can be considered separately for case 18. Complementary retrieval should be tested against the recorded misses, including duplicate plan rows and supplier scope context. These are proposed changes, not implemented fixes or proven improvements. Keep reference answers outside runtime, retain citation validation, and use separate counterfactuals to guard against question-specific behavior.
