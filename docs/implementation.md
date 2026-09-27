# Approved implementation scope

Build FastAPI endpoints `/api/qa`, `/api/documents`, and
`/api/documents/{document_id}/questions`, health, and a plain browser UI.
The canonical request uploads questions JSON and a PDF or JSON source.
Use Python 3.12, page-aware PyMuPDF, LlamaIndex nodes/index/retrieval,
Chroma PersistentClient, explicit gpt-4o-mini generation and
text-embedding-3-small embeddings.

Preserve question order, IDs, duplicates, source context and citations.
Separate answered, partial, not_found and error outcomes. Ignore answer-like
fields in questions files. Support nested source JSON and typed scalar values.
Keep PDF tables page-scoped; do not stitch across pages in baseline.

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
never put source text, prompts, answers or secrets into logs.
