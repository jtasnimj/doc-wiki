# Architecture and assessment tradeoffs

```text
Browser / API client
  → streamed body and questions validation
  → keyed ingestion lock → ready-index reuse
  → JSON record normalization OR bounded PyMuPDF subprocess
  → LlamaIndex TextNodes / SentenceSplitter
  → async shared OpenAI embedding adapter (batched)
  → LlamaIndex VectorStoreIndex / ChromaVectorStore → ready manifest
  → optional question-only plan (disabled by default)
  → LlamaIndex dense retriever → bounded source neighbors
  → async gpt-4o-mini typed outcome → validated public answer
  → citation allowlist + server excerpts → ordered results
```

`app.py` owns HTTP validation and lifecycle, `service.py` coordinates ingestion and per-question outcomes, `json_source.py`/`pdf.py` normalize sources, and `nodes.py`/`retrieval.py` encapsulate LlamaIndex nodes, indexing and retrieval through Chroma. `providers.py` owns explicit paid models, prompts, concurrency, timeouts, retries, and safe errors. `grounding.py` validates internal question plans and typed outcomes; `contracts.py` contains public and evidence schemas. The UI submits both files to `/api/qa` once and renders the ordered response. Ingestion and cache reuse remain internal; there are no public document-management routes.

Manual multipart parsing retains streamed body and part limits. OpenAPI explicitly declares the two required file fields and typed error envelopes for 400/413/415/422/500/502/503/504. Invalid questions fail before paid work. After successful ingestion, answering failures are per-question errors inside an HTTP 200 batch.

LlamaIndex is on the execution path: its `TextNode`, `SentenceSplitter`, embedding adapter, `VectorStoreIndex`, Chroma integration, metadata filters, and retriever are used in tests and the runtime. The application explicitly generates the final answer so provider and citation policies stay in one place. Framework synchronous embedding hooks reject accidental calls; embeddings are prepared asynchronously before indexing or retrieval. No default LLM is instantiated.

## Extraction and provenance

JSON records retain their values and nesting, with bracket-quoted paths and ancestor context. Oversized records are split before narrative chunking. Cumulative normalized-byte and block limits are checked during expansion. PDF text blocks and extracted table rows retain original one-based page numbers and bounding boxes. Headings remain source blocks. Each table row is independently chunked with repeated column labels; a long row may span chunks, each retaining labels and its table location. The table bbox is a source region, not a claim of cell-level coordinates.

Only confidently identified table regions are excluded from narrative text. Ambiguous internal headers are preserved as data with positional columns; bold/color contrast supplies conservative header evidence. Continuation tables stay on their original page. This preserves data while admitting that column semantics on some continuation pages need the source page inspected. No cross-page reconstruction is attempted.

Blocks retain stable document-local identities, order, and parent/group links.
PDF headings require larger typography and conservative layout checks; context
does not carry across pages. Ambiguous layouts may leave context unknown.
Verified headers keep their own bounding boxes, without fixed column-role rules.
Short numbered captions immediately above aligned tables retain their text and
separate locations with each row. Ambiguous or distant text stays independent.
JSON parent context contains complete scalar values within a byte budget; omitted
values are marked and remain indexed at their original paths. Source context is
separate from passage text, with both locations included in citations.

The dense retriever selects seeds first, then attaches at most one predecessor
and successor within the same page/section, table or JSON record. It never expands
neighbors recursively. Seeds take priority within the shared evidence budget;
collection scope and document metadata also constrain added nodes. Retrieval logs
record seed/context counts, token count and latency without text. Evaluation keeps
dense hit@6 separate from complete coverage after expansion. Contextual embedding
text is opt-in and independently versioned in the cache fingerprint; the default
embeds passage text while retaining source context for generation and citations.

PyMuPDF is imported only in the process worker. Each invocation opens and closes its own document and writes serializable results. The small wrapper limits concurrency, includes queue wait in its deadline, terminates on timeout/cancellation, kills after a one-second grace period, reaps the child, and removes temporary output. It does not supervise a general worker pool. Local Chroma, index construction, and file I/O run off the event loop in a single store executor; parser result reads are also offloaded. A cancelled read can finish in its thread, while the API preserves completed question results. A stuck storage mutation can delay cleanup; there is no general hard-kill storage supervisor.

## Reuse and isolation

Document IDs hash source bytes and relevant parser/library/chunk/embedding/vision settings. Fake providers have a separate cache namespace. A per-document application lock prevents duplicate ingestion, and a process-wide storage file lock enforces the single-process deployment. LlamaIndex metadata filters and a separate Chroma collection per document enforce retrieval scope.

The final atomic `ready.json` write records the configuration signature and document counts. Reuse checks the manifest and collection count; missing/invalid readiness is ignored. Every request still uploads both files; the content hash selects an existing ready index internally. Failed work handled by the current request deletes its index and app-owned files. A crash may leave unready files until re-upload or reset. No reservations, index generations, startup staging recovery, retention daemon, or disk quota subsystem exists.

The on-disk cache is for the same local deployment; it is not a portable archival format or a multi-process service. The next deployment step would be server-backed Chroma and shared coordination, after adding authentication and lifecycle controls. The [Chroma client documentation](https://docs.trychroma.com/reference/python/client) describes the local and client/server choices.

## Grounding and deadlines

Questions and evidence are explicitly untrusted data, including injection-shaped source text. Only retrieved IDs may be cited. Source excerpts and locations come from stored evidence, never from model-produced citation text. Schema errors, invalid IDs, refusals, truncated output, and provider failures become execution errors. A not-found answer has no main citations; it may contain up to two short related facts, each with its own validated citations. Empty related information is omitted from serialization. Semantic entailment and relevance are evaluated separately; an ID allowlist does not prove factual correctness.

Generation instructions require explicit evidence for yes/no/non-applicability, distinguish requested subparts from nearby background, and preserve actors, scope, numbers, policy qualifiers and supplier/audit boundaries. Specific missing-information explanations survive validation. `partial` requires an answered requested subpart; a general control near a single unsupported claim belongs in optional related information. The application does not encode company names, question patterns, gold answers or page boosts. The workbook manifest and authored counterfactuals are evaluation-only files.

Structured output uses a root object containing a union of answered, partial,
conflicting and missing outcomes. Claims require source and question-part IDs.
Missing outcomes contain gap phrases and optional separately cited related facts;
other outcomes cannot contain related facts. The server validates IDs and coverage,
formats gap/conflict explanations and constructs the unchanged public response.
Conflicting statements map to `partial`. With planning disabled, the complete
question is one part, so partial coverage still depends on model judgment.

Optional planning sees only the original question. At most twelve exact segments
cover all text and form at most four requested parts plus shared scope. Invalid
rewrites, omitted segments and unknown IDs fail safely. The answer still receives
the complete original question. Planning is disabled pending live semantic tests:
exact-text preservation cannot establish correct decomposition or entailment.
There is no draft critic, repair loop, or question-part retrieval extension.

Identical question strings share a task, including optional planning, while all original entries retain wording, ID, and order. The shared provider semaphore bounds embedding, planning, answer, and optional vision calls across requests. One transient retry and its delay consume the same overall deadline. Answering reserves a small response margin, cancels unfinished tasks, and retains successes. `/healthz` neither touches OpenAI nor performs expensive storage work.

## Deliberate omissions

No OCR, conversation memory, external retrieval, agent tools, hybrid search, reranker, or query rewriting. The approved workbook baseline found missing complementary passages and repeated plan rows in top-six results. Dense seeds now receive bounded source context; the [grounding plan](grounding-fix-plan.md) defines live adoption gates. Local neighbors cannot recover every distant complementary passage. Hash-embedding failures in offline tests are plumbing observations, not a valid reason to tune production retrieval. Figure detection is heuristic and bounded; the optional path has mock verification only.
