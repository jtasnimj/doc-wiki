# Approved implementation scope

Expose `/api/qa` as the only Q&A endpoint, plus health, Swagger documentation,
the raw OpenAPI schema, and a plain browser UI. Every Q&A request uploads
questions JSON and a PDF or JSON source. Use one centered form and ordered
answer cards with citations; no document-preparation or separate question route.
Use Python 3.12, page-aware PyMuPDF, LlamaIndex nodes/index/retrieval,
Chroma PersistentClient, explicit gpt-4o-mini generation and
text-embedding-3-small embeddings.

Preserve question order, IDs, duplicates, source context and citations.
Separate answered, partial, not_found and error outcomes. Ignore answer-like
fields in questions files. Support nested source JSON and typed scalar values.
Keep PDF tables page-scoped; do not stitch across pages in baseline.

Keep the existing success response format. Document typed error envelopes for
400 malformed questions JSON/multipart, 413 oversized uploads, 415 unsupported
formats, 422 validation errors, and 500/502/503/504 execution failures before
answering. Once ingestion succeeds, preserve HTTP 200 with per-question results.

Bound uploads, extraction and provider work. PDF work uses a terminable
subprocess, never concurrent threads. Use an application-wide provider gate,
central retries and deadlines. Cache ready indexes by content/configuration
with a keyed lock and a small manifest. No storage quotas, generations,
reservation system, staging recovery or automatic retention management.

Default tests are offline, using real parsing, LlamaIndex and Chroma with fake
paid providers. Maintain 18 source-reviewed cases, 12 development and six
held-out, and separate extraction/retrieval/answer diagnoses. Only add visual
enrichment or retrieval changes for verified development failures. Vision is
off by default and bounded to three crops/document and two images/answer.

Deliver Docker, lockfile, README, sample requests, evaluation and rubric
evidence. Live calls require separate approval. Local Git commits use the
configured author on feature/doc-wiki-with-rag. No remote publication yet.

Coding conventions: small modules with explicit dependencies; typed public
contracts; thin routes; offline tests of behavior; safe structured logs;
never put source text, prompts, answers or secrets into logs. Use clear names
and straightforward code without new narrative or change-history comments.

## Grounded-answer development increment

Capture the exact 19 workbook questions once before behavior changes, using only
the SOC 2 PDF as runtime evidence. Keep workbook answers outside generation;
ignore comments and confidence. Preserve ranked retrieval, actual results,
citations, warnings, configuration, latency and usage. Review reference alignment
and PDF correctness separately, with an individual diagnosis and fix for every case.

Generate concise answers with requested-subpart coverage and explicit support for
yes/no/N/A. Preserve scope, actor, numbers and qualifications. Distinguish criteria,
implemented controls, supplier responsibilities and audit findings. Replace forced
generic abstention with a specific gap explanation. Only not_found may include
optional related_information, at most two short directly related facts with separate
citations. Server-derived excerpts and ID allowlisting remain authoritative.
Invalid/missing related citations are execution errors. Omit empty related facts;
render them safely under a distinct heading and preserve them in JSON export.

Do not hardcode answers, question matching, company rules or page boosts. Keep dense
retrieval initially and propose changes only against observed misses. Add authored
paraphrased/counterfactual development cases for all failure patterns, explicit
negatives, supported non-applicability and weak evidence. Preserve the original
held-out suite. Mock tests verify contracts, not semantic model quality.

The approved one-time baseline has 19 questions and a disclosed conservative
$0.14 estimate. Any post-change paid evaluation needs its own approval. Deliver
the 19-row review with honest pending retest outcomes, offline checks, browser
checks and a local commit. No storage reset or model/stack/vision change.
