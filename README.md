# DocWiki

A local document-Q&A assessment application. Upload questions JSON and a PDF or JSON source to get ordered answers, explicit missing-information responses, and source citations.

Python 3.12 · FastAPI · direct PyMuPDF · LlamaIndex · Chroma PersistentClient · OpenAI `gpt-4o-mini` and `text-embedding-3-small` · plain browser UI.

## Run locally

Install Python 3.12 and [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync --frozen --group dev
cp .env.example .env
# Set OPENAI_API_KEY in .env using your editor; keep it server-side.
uv run uvicorn docwiki.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Open <http://127.0.0.1:8000>. Health and the UI work without a key; ingestion/answering requires one. Normal application requests with a configured key incur provider charges. Interactive Swagger API documentation is at `/docs`, with the raw schema at `/openapi.json`. Swagger loads its JavaScript/CSS from jsDelivr; the document-Q&A UI itself needs no CDN or JavaScript build.

Use **one API process per data directory**. A file lock enforces this. The default `data/` stores original uploads, normalized extraction, ready manifests, optional image crops, and Chroma vectors. `.env`, instructions, uploads, indexes, test artifacts, and evaluation runs are ignored by Git; Docker copies only the application and its locked dependencies.

## API

| Route | Input | Result |
|---|---|---|
| `POST /api/qa` | Multipart `questions_file`, `document_file` | Ordered batch answers |
| `GET /healthz` | None | `{"status":"ok"}`, no provider call |
| `/docs` | Browser | Interactive API documentation and file-upload controls |
| `/openapi.json` | None | Machine-readable API schema |
| `/` | Browser | Centered two-file form, ordered answers, citations, JSON export |

Canonical JSON-source request:

```bash
curl --fail-with-body http://127.0.0.1:8000/api/qa \
  -F 'questions_file=@examples/questions.json;type=application/json' \
  -F 'document_file=@examples/source.json;type=application/json'
```

PDF-source request (uses the redistributable synthetic fixture):

```bash
curl --fail-with-body http://127.0.0.1:8000/api/qa \
  -F 'questions_file=@examples/questions.json;type=application/json' \
  -F 'document_file=@evaluation/sources/policy.pdf;type=application/pdf'
```

Every submission sends both files in one request. Re-uploading the same document with the same relevant configuration automatically reuses its ready index, including across restarts. The returned document ID identifies the source; there is no separate document-management or single-question endpoint. To ask one question, upload a JSON list containing one entry.

Questions files accept a list of strings, a list of records, or a mixture, optionally wrapped in `questions`:

```json
{"questions":["Which cloud provider?",{"id":"sla","question":"What numeric notification SLA is stated?","answer":"ignored"}]}
```

IDs are generated where absent. Duplicate explicit IDs, blank questions, non-string IDs/questions, and excess questions are rejected before paid work. Wording, order, and duplicate questions are preserved; identical question strings share computation within a batch. Existing `answer`, `comments`, or `confidence` in the questions file are ignored.

Source JSON accepts objects and arrays, nested records, and source Q&A records. It preserves scalar types and exact record paths such as `$[0]["hosting"]`, with ancestor fields when splitting. Top-level primitives, duplicate object keys, non-finite numbers, and empty/non-informative documents are rejected. `false`, `0`, and `null` remain in otherwise informative records. Workbook columns would naturally become JSON keys, with one object per row, but **XLSX upload is outside scope**.

The response contains `document_id`, `results`, `warnings`, and `batch_status`. Each result has `id`, original `question`, `answer`, `status`, `citations`, and nullable `error`:

| Status | Meaning |
|---|---|
| `answered` | Supported answer, with citations |
| `partial` | Supported portions plus missing information, or explicitly conflicting evidence |
| `not_found` | Short explanation of the specific missing information; no answer citations |
| `error` | Null answer; safe `{code, message}` execution error |

Citations contain a stable source ID, server-derived excerpt, kind, and locations: one-based PDF page plus `[x0,y0,x1,y1]` in PDF points, or an exact JSON record path. Optional visual descriptions are labeled `derived: true`. Citation validation checks identity/provenance and required presence; semantic support still needs evaluation.

A `not_found` result may also contain `related_information: [{"text": "…", "citations": [...]}]`: at most two short, directly relevant facts, each with its own citations. These appear under **Related information** and cannot establish a yes/no answer. The field is omitted when empty and for other statuses. Missing or invented related citations become execution errors. For example, a documented authentication control does not establish a failed-login lockout threshold. No retrieved evidence still produces a generic abstention.

Once ingestion succeeds, a batch returns HTTP 200 even if every question fails. `batch_status` is `completed`, `partial_failure`, or `failed`; `partial` answers and `not_found` are successful executions. Answering deadlines preserve finished results and mark unfinished entries `request_timeout`.

Request/document-level errors use the typed `{ "error": { "code": "...", "message": "..." }, "request_id": "..." }` envelope. Swagger includes the schema, descriptions, and examples for each response:

| HTTP status | Meaning |
|---|---|
| 400 | Malformed questions JSON or multipart encoding |
| 413 | An uploaded file or the whole request exceeds its size limit |
| 415 | Unsupported file type |
| 422 | Missing/incorrect file fields, invalid questions, or invalid source content |
| 500 | Unexpected server failure |
| 502 / 503 / 504 | Provider failure, unavailability, or deadline during document ingestion |

Select both files in the centered form and click **Answer questions**. Results appear below as ordered cards with status, answer, and expandable source excerpts. Changing either file clears the previous results and export state. Inputs are disabled while processing; warnings and safe errors remain visible. **Export JSON** downloads the response unchanged.

## Limits and controls

| Resource | Default |
|---|---|
| Document / questions file / whole multipart body | 10 MiB / 256 KiB / 11 MiB |
| PDF pages / questions / characters per question | 150 / 20 / 2,000 |
| JSON depth / values / normalized text / chunks | 32 / 100,000 / 10 MiB / 2,000 |
| Narrative chunk / overlap / dense retrieval / evidence | ~700 tokens / 100 / top 6 / 6,000 tokens |
| Application-wide provider concurrency / call timeout | 4 / 30 seconds |
| PDF extraction concurrency / deadline | 1 / 90 seconds |
| Overall request deadline | 180 seconds, including queues and retries |

Configuration fields in `src/docwiki/config.py` use the `DOCWIKI_` prefix; the key is `OPENAI_API_KEY`. There is one centralized transient retry; SDK retries are disabled. Quota exhaustion pauses further calls until restart. No implicit embedding, OCR, or layout models are downloaded. A tokenizer vocabulary is bundled with its license.

Dense retrieval keeps the top-six seeds first, then adds at most one predecessor
and successor per seed within its page-scoped section or JSON record. All evidence
shares the 6,000-token limit and each passage retains its own citation identity.
`DOCWIKI_CONTEXT_NEIGHBORS=false` disables expansion for a controlled comparison.
Heading/parent context retains its source locations. The new parser/chunker version
creates fresh indexes on the next upload; existing stored indexes are retained.

Two evaluation options remain off by default: `DOCWIKI_CONTEXTUAL_EMBEDDINGS=true`
includes inherited context in embedding text and creates a separate cache entry;
`DOCWIKI_QUESTION_PLANNING=true` makes one question-only planning call per unique
question before retrieval. Plans must preserve the complete original text and
every part must be addressed in the answer. Exact spans and valid citations do not
prove semantic correctness. Enabling planning adds latency and paid usage; evaluate
each option separately with approved live cases before adopting it. No additional
question-part searches are enabled.

## Verify offline

```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src/docwiki
uv run pytest -m "not live"
uv run python -m docwiki.eval --mode offline
docker build -t docwiki:local .
```

Tests use actual multipart requests, parsing, chunking, LlamaIndex indexing/retrieval, and Chroma with deterministic fake providers. They never require a key. The offline evaluator does **not** measure OpenAI quality. See [evaluation observations](docs/evaluation.md), [review resolutions](docs/review.md), and the [rubric evidence matrix](docs/evidence.md).

The 19-question paid development evaluation exposed unsupported claims and missing
complementary evidence. The [general grounding fixes](docs/grounding-fix-plan.md)
implement source context, bounded neighbors and typed outcomes; live semantic
retesting remains pending.
Evaluation manifests and authored counterfactuals remain separate from runtime
generation. Offline tests verify application behavior, not semantic answer quality.

For an explicit fake-provider browser session:

```bash
uv run python -m tests.browser_server
# Separately, with Playwright and Chromium installed:
node tests/browser-smoke.cjs
# BROWSER_CHANNEL=chrome can select an existing Chrome installation.
```

This helper uses port 8765 and temporary storage. It is separate from the application entry point. Browser screenshots go to ignored `artifacts/`. The main CI workflow runs offline Python checks, evaluation, and a container health smoke test.

## Docker and reset

```bash
docker build -t docwiki:local .
docker volume create docwiki-data
docker run --rm --name docwiki -p 127.0.0.1:8000:8000 \
  --env-file .env -v docwiki-data:/app/data docwiki:local
```

The image runs one Uvicorn process as UID 10001. For a host bind mount, grant that UID write access to the chosen data directory. The named volume persists across container restarts. Application events are structured JSON with request IDs, HTTP status/latency, ingestion timing/counts/cache results, provider/model, retries, provider latency, and reported token usage. Document text, questions, answers, uploaded filenames, and credentials are omitted. Uvicorn startup/access messages use its standard format. `tests/test_observability.py` verifies the JSON fields and sensitive-data exclusion with an offline SDK transport; no separate metrics service is required.

Stop the server before resetting. Reset removes the app-managed uploads, crops, and indexes under the configured directory:

```bash
uv run python -m docwiki.reset --yes
# For the stopped container's named volume:
docker run --rm -v docwiki-data:/app/data docwiki:local python -m docwiki.reset --yes
```

No automatic eviction or retention policy runs. Interrupted ingestion without a valid ready manifest is ignored and can be replaced on re-upload; explicit reset removes abandoned data. Local persistent storage is an assessment tradeoff. Production extensions include authentication/authorization, quotas, recovery, retention controls, server-backed storage, and deployment hardening. IDs are not access controls; keep this demo local.

## Evaluation and delivery boundaries

The baseline has page-scoped PDF tables, dense retrieval, and vision disabled. No cross-page stitching, OCR, BM25, reranking, rewriting, or agents are included. Ambiguous table headers retain positional columns and all rows, with a warning. Image-only PDFs are rejected; mixed PDFs report pages with limited text. Figures and unusual layouts can lose information.

Source inspection verified a development question whose answer appears only in a diagram. The bounded optional vision path is implemented and tested with mocks: `DOCWIKI_VISION_ENABLED=true` permits up to three PyMuPDF crops per document, cached `gpt-4o-mini` descriptions, and at most two original images per answer. It remains off by default and has not had paid quality evaluation. See [the recorded gate](docs/evaluation.md#figure-gate).

Live tests require separate approval with an explicit case count and estimated cost. `uv run python -m docwiki.eval --mode estimate --split dev` makes no calls. After approval, the evaluator also requires `DOCWIKI_LIVE_APPROVED=1` and sufficient `--budget-usd`; see the evaluation document. Verify embedding-model access first, stop on quota errors, and reserve part of the assessment's $5 budget for the demonstration. Usage estimates do not establish the key's remaining balance.

Original assessment files stay in ignored `instructions/`; only authored fixtures are included. Review [dependency licensing and redistribution](docs/licenses.md) before submission. No project license has been selected. Commits remain local on `feature/doc-wiki-with-rag`. Automated verification remains offline; paid evaluation and publication require separate approval. Container execution remains unverified after the earlier Colima/containerd disk-full build failure.
