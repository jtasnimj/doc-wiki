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

Open <http://127.0.0.1:8000>. Health and the UI work without a key; ingestion/answering requires one. Normal application requests with a configured key incur provider charges. The generated API schema is at `/openapi.json`; the browser UI needs no CDN or JavaScript build.

Use **one API process per data directory**. A file lock enforces this. The default `data/` stores original uploads, normalized extraction, ready manifests, optional image crops, and Chroma vectors. `.env`, instructions, uploads, indexes, test artifacts, and evaluation runs are ignored by Git; Docker copies only the application and its locked dependencies.

## API

| Route | Input | Result |
|---|---|---|
| `POST /api/qa` | Multipart `questions_file`, `document_file` | Ordered batch answers |
| `POST /api/documents` | Multipart `document_file` | Ready document ID, page/chunk counts, warnings, cache hit |
| `POST /api/documents/{document_id}/questions` | JSON `{"questions": [...]}` | Answers using the existing index |
| `GET /healthz` | None | `{"status":"ok"}`, no provider call |
| `/` | Browser | Upload, prepare, batch/single questions, citations, JSON export |

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

Prepare once and reuse the returned ID:

```bash
curl --fail-with-body http://127.0.0.1:8000/api/documents \
  -F 'document_file=@examples/source.json;type=application/json'

curl --fail-with-body http://127.0.0.1:8000/api/documents/DOCUMENT_ID/questions \
  -H 'Content-Type: application/json' \
  -d '{"questions":[{"id":"hosting","question":"Which cloud provider is used?"}]}'
```

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
| `partial` | Supported portions plus an explicit account of missing information |
| `not_found` | Exactly “Not found in the provided document.”, no citations |
| `error` | Null answer; safe `{code, message}` execution error |

Citations contain a stable source ID, server-derived excerpt, kind, and locations: one-based PDF page plus `[x0,y0,x1,y1]` in PDF points, or an exact JSON record path. Optional visual descriptions are labeled `derived: true`. Citation validation checks identity/provenance and required presence; semantic support still needs evaluation.

Once ingestion succeeds, a batch returns HTTP 200 even if every question fails. `batch_status` is `completed`, `partial_failure`, or `failed`; `partial` answers and `not_found` are successful executions. Answering deadlines preserve finished results and mark unfinished entries `request_timeout`. Document-level errors use 422 for invalid content, 413 for size limits, 415 for unsupported types, 404 for missing ready documents, and 502/503/504 for provider or deadline failures. Error responses contain a safe code/message and request ID.

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

The image runs one Uvicorn process as UID 10001. For a host bind mount, grant that UID write access to the chosen data directory. The named volume persists across container restarts. Logs are structured JSON with IDs, timings, counts, cache results, safe errors, and provider usage; document text and credentials are omitted.

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

Original assessment files stay in ignored `instructions/`; only authored fixtures are included. Review [dependency licensing and redistribution](docs/licenses.md) before submission. No project license has been selected. Commits remain local on `feature/doc-wiki-with-rag`; remote publication and paid calls have not been performed. Container execution is pending a working local Docker daemon.
