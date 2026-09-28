# Evaluation observations

The frozen case manifest is `evaluation/cases.json`: 12 development cases and six held-out cases, each with source SHA-256, question, expected status, required facts, forbidden claims, and acceptable PDF pages or JSON paths. The first five are the supplied assessment questions. Source Q&A records are legitimate evidence only when uploaded as the source; reference answers in the case manifest never enter the runtime index or prompt.

The implementer inspected the sources, including rendered PDF pages 15 and 31, narrative text on page 21, and the third-party table on page 17. Source review does not mean human sign-off or proven model quality; those remain explicitly pending in the case records. The original XLSX answer/confidence columns were not adopted as PDF truth. Region absence was checked against the extracted report and the infrastructure diagram; “without undue delay” was not converted to a numeric commitment.

## Reproduce

```bash
uv run python -m docwiki.eval --mode offline --split dev
uv run python -m docwiki.eval --mode offline --split heldout
```

The default `--split all` runs all 18. The evaluator uses a temporary data directory, real normalization/chunking/indexing/retrieval, and deterministic fake providers. It verifies hashes before running a case. The original PDF belongs at `instructions/Nave-SOC2-Type-2-Report.pdf`; without it, seven development cases are explicitly skipped. CI therefore runs the 11 distributable cases unless the original is separately supplied. A hash mismatch is also reported as a skip requiring renewed source review, never silently treated as the same source.

Full local runs with excerpts are saved to ignored `evaluation/runs/`. The committed [offline-results.json](offline-results.json) contains only aggregate and diagnostic measurements, without retrieved passages.

## Observed offline result

All 18 cases ran locally with no skipped sources. The final run used parser `page-blocks-v2`, top-six dense retrieval, 700-token chunks, 100-token overlap, and 64-dimensional **fake hash embeddings**. No parameter tuning used the held-out results.

| Metric | Development | Held-out | Combined |
|---|---:|---:|---:|
| Cases executed | 12 | 6 | 18 |
| All required evidence extracted, among positive text/table cases | 10/10 | 4/4 | 14/14 |
| Evidence hit@6 | 5/10 | 4/4 | 9/14 (64.3%) |
| All required evidence retrieved | 5/10 | 4/4 | 9/14 (64.3%) |
| Citation structural validity | 12/12 | 6/6 | 18/18 |
| Factual correctness / citation entailment | Not measured | Not measured | Not measured |
| Answer-status / abstention quality | Not measured | Not measured | Not measured |
| Paid usage | $0 | $0 | $0 |

`not_found` cases have no required positive evidence and do not enter extraction/retrieval denominators. Citation validity includes valid no-citation abstentions; it is not a citation-support score. Each required-evidence group must match both its location and expected text. This is a targeted recall check, not a full-document extraction accuracy claim.

The fake retriever missed development cases 01, 02, 03, 05, and 06; the required evidence was present in extraction. These diagnose the fake retrieval stage. They do not establish the behavior of `text-embedding-3-small`, and no BM25/reranker/stitching change was justified from them. Fake generation is deliberately a stub, so publishing its apparent answer accuracy would be misleading.

On this local run, the first sample-PDF case including ingestion took 6,060 ms; subsequent cached cases took 2–13 ms, and first synthetic-PDF ingestion took 109 ms. These use fake providers on one machine, with no network latency, and are not production performance claims. Per-case latency is in the committed result artifact. This original 18-case suite has not had a paid run. The separate [19-question workbook baseline](workbook-review.md) records actual OpenAI usage and reviewed failures; its [post-change live retest](live-retest-20260928.md) found unchanged status agreement, persistent unsupported claims and one invalid-citation error.

## Figure gate

Development case 12 asks which Google Cloud runtime hosts Nave App in the primary infrastructure diagram. Page 15 visibly labels the app with **App Engine**, but “App Engine” is absent from the full baseline text/table extraction. The bounded candidate detector identified that page. This is a verified extraction failure, independent of retrieval and generation.

The optional enhancement is therefore implemented behind `DOCWIKI_VISION_ENABLED=false` by default. It renders at most three candidate page/crops per document, up to four million pixels each; uses `gpt-4o-mini` descriptions; stores derived provenance and original crops; and passes at most two retrieved original images to an answer. The ready-index cache includes vision configuration, so reuse does not regenerate descriptions. Candidate detection remains heuristic and reports coverage/budget warnings. It does not recover fully scanned PDFs, which the baseline rejects before enrichment.

`tests/test_vision.py` verifies disabled behavior, the three-crop cap, reuse, derived citations, and the two-image answer cap with fake responses. It does not claim App Engine was correctly read by a live model. Baseline case 12 expects abstention and a coverage warning; its separate vision expectation is recorded for a future approved comparison. No paid vision run has occurred, and the CLI's baseline live evaluator forces vision off.

## Live evaluation, only after separate approval

Get an explicit approved case count and cost budget first. Estimate without making calls:

```bash
uv run python -m docwiki.eval --mode estimate --split dev
```

Current text-only estimates including one retry are $0.1590 for 12 development cases, $0.1915 for six held-out cases with three sources, and $0.2946 for all 18 with four sources. These deliberately allow the maximum configured document chunks; a fresh run may ingest more than a cached API request. Estimates use $0.02/M embedding tokens and $0.15/M input, $0.60/M output generation tokens from the [embedding model page](https://developers.openai.com/api/docs/models/text-embedding-3-small) and [GPT-4o mini model page](https://developers.openai.com/api/docs/models/gpt-4o-mini). Verify current pricing before approval. Vision has separate image-token costs and needs its own bounded estimate.

Once a development run has actually been approved, its explicit command is:

```bash
DOCWIKI_LIVE_APPROVED=1 uv run python -m docwiki.eval \
  --mode live --split dev --budget-usd 0.16 \
  --output evaluation/runs/live-dev.json
```

The environment flag is an execution guard, not a substitute for approval. The first ingestion verifies embedding-model access; auth/model-access or quota errors stop further evaluation. There is no automatic model substitution. Reserve budget for the demonstration and check the account separately; logged usage is not its remaining balance. Cost calculated from reported successful-call usage can omit unreported failed-call billing and is an estimate, not a dollar-enforcement service.

The live report includes source evidence, required facts, forbidden claims, and empty human-review fields. A reviewer must mark factual correctness and citation support, checking that every factual claim is entailed and every requested subpart is addressed or identified as missing. Also inspect `not_found` accuracy and false abstention. Diagnose failures in order: extraction → retrieval → answer. Tune only on development cases, then run held-out once the configuration is frozen. Preserve contrary evidence in the retention-conflict case; never infer an undisclosed deadline or region.
