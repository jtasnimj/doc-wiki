# General grounding fixes

Proposed implementation plan; implementation has not started. Live evaluation
still requires separate approval. The user chose to keep `gpt-4o-mini` fixed and remove
the previous grounding/workbook reports, raw paid traces and rejected prototypes.
The proposed scope below covers the three demonstrated failure areas; scope
selection is still pending.

## Worth fixing

| Priority | Problem | General remedy | Evidence required before adoption |
|---|---|---|---|
| 1 | Document meaning is lost between extraction and indexing | Preserve heading, parent, ordering and table-header provenance through nodes and evidence | Real PDF/JSON tests preserve meaning and source locations without inventing context |
| 2 | Relevant hits omit complementary facts | Retrieve precise passages and attach bounded source context; evaluate additional question-part retrieval only if needed | More complete required evidence at the same evidence budget, without losing previously supported cases |
| 3 | Answers silently weaken the question's scope | Preserve the original question and explicitly account for its requested parts and defining qualifiers | Source-reviewed answers respect scope, numerical commitments, negatives and non-applicability on unrelated documents |
| Supporting fix | Internally inconsistent output becomes avoidable execution errors | Use distinct internal outcome shapes and server validation | Invalid combinations cannot pass; legitimate absence remains distinct from execution failure |

Keep FastAPI, PyMuPDF, LlamaIndex, Chroma, `gpt-4o-mini`,
`text-embedding-3-small`, the two-file `/api/qa` workflow and the public response.
Keep the 6,000-token evidence limit, provider concurrency/deadlines, source
isolation, content-hash reuse and vision defaults. Do not implement storage
infrastructure or change the UI as part of this work.

## 1. Preserve document structure

Work in extraction, evidence contracts and node creation.

- Give source blocks stable document-local identities, reading order and explicit
  parent/neighbor relationships. Preserve existing PDF page/bbox and JSON paths.
- Detect headings conservatively from layout and typography. The current rule
  treats short text as a possible heading; do not propagate every short line as
  authoritative section context. Use unknown when structure is ambiguous.
- Keep verified headings and parent context with child nodes. Separate source
  text from contextual metadata and retain the locations of both.
- Keep table rows with column labels, table captions and header provenance.
  Recover labels only from verifiable source layout. Never assume that a fixed
  column number means criterion, control, test or finding. If a continuation page
  has no reliable header, preserve the row with unknown column roles.
- Keep continuation tables page-scoped. Do not introduce cross-page header
  inheritance or table reconstruction in this increment.
- Preserve structured JSON ancestor context when records split. Do not silently
  truncate a parent value into misleading text; use explicit bounded context and
  retain links to its exact source record.
- Version parser/chunker metadata in the existing cache fingerprint. New indexes
  must not reuse incompatible old metadata; do not delete existing stored indexes.

Tests use authored documents with reordered columns, ambiguous headers, headings,
lists, page boundaries and nested JSON. No report-specific layouts or vocabulary
belong in the implementation.

## 2. Retrieve complete evidence within a fixed budget

Keep LlamaIndex responsible for node indexing and dense retrieval. First retrieve
the existing top-six seeds, then use their source relationships to attach small
parent/adjacent passages. Begin with at most one predecessor and one successor
within a verified section or JSON record, preserve all seed passages that fit,
deduplicate by source identity, and cap the combined payload at 6,000 tokens.
Do not attach a whole page, whole document or neighboring unrelated section.
Every added passage has its own source identity/location and can be cited.

Test context expansion as a separate change from new embeddings of contextual
nodes. Measure complete evidence coverage as well as hit@6; a single relevant hit
does not establish that all required facts were retrieved. Log counts, latency
and usage without logging source text or questions.

Some known missing passages are far from the top-ranked passage. Local context
expansion is not expected to solve all of them. If the development evaluation
still demonstrates these misses, evaluate one bounded extension: the original
query plus at most three searches for explicit parts of the same question. Use
question text only, batch their embeddings, and keep the same final evidence
budget. No free-form query rewriting, external search, iterative search loop or
answer-driven search. Adopt only if complete evidence improves without a loss
of necessary evidence on previously supported cases.

## 3. Preserve the question independently of the evidence

The prior single-call evidence plan dropped qualifications while selecting
evidence. Do not reuse it or the failed draft-review pass.

Evaluate a small question-only planning step before evidence selection. Its input
is the original question, with no document, draft answer or reference answer.
Its output identifies independently requested parts and shared scope using
verbatim question spans. Preserve the original question unchanged throughout.
Verify referenced spans and require that the plan accounts for the complete
question; reject unsupported rewrites. A defining qualification stays attached
to its claim and cannot become an independently answered background question.

Do not split at every conjunction: an alternative, a list of conditions and
independent questions have different meanings. Include counterexamples for each.
Exact-span checks establish preservation, not correct semantic decomposition;
source-reviewed model tests must verify that distinction before adoption.

Use at most one planning call per unique question and one answer call. Reuse the
plan for the optional question-part searches. No recursive planning, automatic
review chain or repeated repair calls. All calls and retries consume the existing
request deadline and provider gate. If the planning experiment does not improve
the semantic cases, do not make it a mandatory production dependency.

## 4. Encode outcome rules and retain citation authority

Use an internal wrapper with separate answerable, partial and missing outcome
variants; translate it to the unchanged public response on the server.

- Answerable outcomes require supported claims and citations. Explicitly
  supported Yes, No and non-applicability are all possible answered results.
- Partial outcomes require at least one independently answered part plus a
  specific missing part, or explicitly conflicting evidence. Generic background
  about one unsupported scoped claim does not make it partial.
- Missing outcomes explain the missing information. Optional related facts have
  separate citations and do not appear as an answer to the question.
- Do not allow related-information fields in answered/partial variants. Require
  citation references on supported claims. Avoid asking the model to reproduce
  verbatim quotes; provide stable passage/span identifiers and construct excerpts
  from the source on the server.
- Verify all referenced question/evidence identifiers, source isolation, status
  invariants and required coverage entries. Refusals, invalid outputs and provider
  failures remain execution errors. Do not silently turn them into not_found.

The SDK schema should use a nested union inside a root object and be tested
against the supported schema subset. Structured Outputs constrains shape but
can still contain semantic mistakes; it does not prove claim support.
[Official Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

Model decisions about entailment remain a measured risk with the fixed model.
Do not present either exact-span preservation or citation allowlisting as a
semantic guarantee. No keyword-based downgrade rules, unsupported numerical
confidence thresholds or answer templates keyed to evaluation cases.

## Verification and delivery

1. Keep the 19 workbook cases and authored generalization cases as development
   fixtures; preserve the original held-out suite. Runtime code never imports
   evaluation manifests or reads workbook answers.
2. Add real-path regressions before each deterministic fix: extraction/node
   context, retrieval expansion, source isolation, output variants, deadlines,
   duplicate-question reuse and cache compatibility.
3. Extend paired semantic cases across unrelated domains: change only actor,
   scope, threshold, time commitment, positive/negative evidence or applicability.
   Also shuffle evidence order and table columns, add irrelevant controls, and
   test contradictions and injection-shaped text. Include both PDF and JSON.
4. Run lint, formatting, type checks and offline tests. Mocked answers verify
   plumbing only. Check the browser/API for unchanged ordered results, citations,
   related facts and JSON export.
5. Obtain separate approval for exact live case counts and cost before model
   calls. Compare one change at a time. Raw historical traces are being deleted,
   so a new controlled baseline is needed for a reliable before/after comparison.
6. Require zero unsupported affirmative/negative/non-applicability conclusions
   on the targeted failure controls, no regression on supported controls, no new
   structural execution errors, and improved complete evidence coverage without
   exceeding limits. Review every live answer and citation against the source.
   Then freeze the candidate and evaluate held-out cases without tuning on them.
7. Commit only verified increments locally. Do not claim the fixed model meets
   the quality target if the semantic gate fails. Report the remaining limitation
   instead of changing models or adding speculative retrieval components.

Do not pursue BM25/MMR/deduplication as standalone quality fixes, another
same-model draft critic, OCR/vision, agents, rerankers, cross-page stitching,
infrastructure expansion, or matching unsupported workbook reference claims in
this scope. Previous experiments do not justify those additions.

## Cleanup completed

Removed the old grounding-debug, paid-retest and workbook-review Markdown reports,
their generated HTML/JSON reports, paid captures, related screenshots and debug
prototypes. Documentation links now point to this implementation plan. Source
documents, evaluation fixtures/tests, current indexes, architecture/setup
documentation and concise limitations in the rubric matrix remain. Git history
was not rewritten. All 111 offline tests and documentation-link checks pass.
