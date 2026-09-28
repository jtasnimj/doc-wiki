# doc-wiki

A document question-answering API and browser interface built with FastAPI, LlamaIndex, and OpenAI. Upload a PDF or JSON document with a set of questions to receive ordered answers, source citations, and explicit responses when information is missing.

## Features

- **PDF and JSON sources:** Extract PDF text and page-scoped tables, or read nested JSON records while preserving source locations.
- **Document-grounded answers:** Retrieve relevant passages and generate answers using `gpt-4o-mini`.
- **Traceable citations:** Return PDF page numbers and bounding boxes, or JSON record paths, with source excerpts.
- **Persistent indexing:** Reuse Chroma indexes for repeated uploads with matching configuration, including after a restart.
- **Batch processing:** Preserve question order and IDs, with per-question statuses and errors.
- **Browser interface:** Upload both files, inspect answers and citations, and export the response as JSON.
- **Operational controls:** Validate uploads, bound provider concurrency, apply deadlines and retries, and emit structured logs.

## Technology stack

| Component | Technology |
|---|---|
| Runtime and API | Python 3.12, FastAPI, Pydantic, Uvicorn |
| PDF extraction | PyMuPDF |
| Retrieval and vector storage | LlamaIndex, persistent Chroma |
| Answer generation | OpenAI `gpt-4o-mini` |
| Embeddings | OpenAI `text-embedding-3-small` |
| Browser interface | HTML, CSS, JavaScript |
| Development | uv, pytest, Ruff, mypy, Docker |

## Installation

Install Python 3.12 and [uv](https://docs.astral.sh/uv/), then run these commands from the project directory:

```bash
cd doc-wiki
uv sync --frozen --group dev
cp .env.example .env
```

Edit `.env` and set your server-side OpenAI API key:

```dotenv
OPENAI_API_KEY=your_openai_api_key_here
```

The project/distribution name is `doc-wiki`; its Python package is `doc_wiki`, since Python import identifiers cannot contain hyphens. Environment variables retain the `DOCWIKI_` prefix.

## Usage

### Start the server

```bash
uv run uvicorn doc_wiki.app:app --host 127.0.0.1 --port 8000 --workers 1
```

- Browser interface: <http://127.0.0.1:8000>
- Interactive API documentation: <http://127.0.0.1:8000/docs>
- OpenAPI schema: <http://127.0.0.1:8000/openapi.json>

The browser interface and health endpoint work without an API key. Document ingestion and answering require a key and incur provider charges. Run one API process per data directory; a file lock enforces exclusive access.

### Try the included example

[examples/source.json](examples/source.json) contains a fictional company's hosting and incident-response details. [examples/questions.json](examples/questions.json) asks about its hosting provider, primary region, and a numerical notification deadline that the source deliberately does not specify.

```bash
curl --fail-with-body http://127.0.0.1:8000/api/qa \
  -F 'document_file=@examples/source.json;type=application/json' \
  -F 'questions_file=@examples/questions.json;type=application/json'
```

You can upload the same two files through the browser interface and choose **Answer questions**, then **Export JSON** to download the response.

For a PDF example, use the included synthetic policy and its matching questions:

```bash
curl --fail-with-body http://127.0.0.1:8000/api/qa \
  -F 'document_file=@evaluation/sources/policy.pdf;type=application/pdf' \
  -F 'questions_file=@examples/pdf-questions.json;type=application/json'
```

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/healthz` | Returns `{"status":"ok"}` without a provider call |
| `POST` | `/api/qa` | Accepts multipart `document_file` and `questions_file` uploads |

Every Q&A request includes both files. Identical document uploads reuse a ready index when the relevant configuration matches. To ask one question, submit a questions file containing one entry.

### Questions format

```json
{
  "questions": [
    {"id": "hosting", "question": "Which cloud provider hosts Example Company?"},
    {"id": "region", "question": "What is the primary hosting region?"},
    {"id": "notification", "question": "Within how many hours must customers be notified of an incident?"}
  ]
}
```

A plain array of strings or records is also accepted, including mixed arrays. Missing IDs are generated. Duplicate explicit IDs, blank questions, and invalid types are rejected. Extra fields such as existing `answer`, `comments`, and `confidence` values are ignored. Question wording, order, and duplicate questions are preserved.

### Response format

The following illustrates the response structure for the JSON example. Answer wording and generated identifiers vary; this is not a captured live-model result. The first result is shown for brevity, while the API returns one result per question.

```json
{
  "document_id": "<generated-document-id>",
  "results": [
    {
      "id": "hosting",
      "question": "Which cloud provider hosts Example Company?",
      "answer": "Example Company is hosted by ExampleCloud.",
      "status": "answered",
      "citations": [
        {
          "source_id": "<generated-source-id>",
          "kind": "json",
          "locations": [{"page": null, "bbox": null, "json_path": "$"}],
          "excerpt": "<server-derived source excerpt>",
          "derived": false
        }
      ],
      "error": null
    }
  ],
  "warnings": [],
  "batch_status": "completed"
}
```

| Result status | Meaning |
|---|---|
| `answered` | A supported answer with citations |
| `partial` | Supported portions with missing information, or conflicting evidence |
| `not_found` | The requested information is absent; no answer citations |
| `error` | Processing failed; `answer` is null and `error` contains a safe code and message |

For the notification example, the expected behavior is to explain that “without undue delay” does not specify a number of hours. A `not_found` result can include up to two separately cited `related_information` facts. These do not establish the missing answer.

PDF citations use one-based page numbers and bounding boxes in PDF points. JSON citations use exact record paths. Optional visual descriptions are marked `derived: true`.

After successful ingestion, the API returns HTTP 200 with `batch_status` set to `completed`, `partial_failure`, or `failed`, even if all questions fail. `partial` and `not_found` count as successful executions.

Request-level errors have this shape:

```json
{
  "error": {"code": "invalid_questions", "message": "Supply 1–20 questions."},
  "request_id": "<request-id>"
}
```

| HTTP status | Meaning |
|---|---|
| 400 | Malformed questions JSON or multipart encoding |
| 413 | File or request size limit exceeded |
| 415 | Unsupported file type |
| 422 | Invalid fields, questions, or document content |
| 500 | Unexpected server failure |
| 502 / 503 / 504 | Provider failure, unavailability, or ingestion deadline |

## Supported documents

**PDF:** Text-bearing PDFs, with page-level source locations and page-scoped table extraction. Image-only PDFs are rejected; mixed PDFs can produce warnings for pages with limited text. OCR and cross-page table stitching are not included.

**JSON:** Objects and arrays, including nested records and source Q&A records. Scalar types and record paths are preserved. Top-level primitives, duplicate keys, non-finite numbers, and empty or non-informative content are rejected. XLSX is not supported.

## How it works

1. **Validate:** Check multipart fields, document size, and question structure before paid processing.
2. **Extract:** Read PDF text/tables or JSON records and retain their source locations.
3. **Chunk and index:** Split content into bounded passages, embed them, and persist vectors and document artifacts locally.
4. **Retrieve:** Select the top six dense-retrieval passages, then add bounded neighboring context within the same section or record, subject to a shared token budget.
5. **Answer:** Send the original question and retrieved evidence to the model and validate the structured answer and citation identities.
6. **Return:** Preserve question order and report answers, missing information, warnings, and individual failures.

Citation validation checks provenance and required presence. It does not independently prove that every claim is semantically supported.

## Configuration

Copy defaults from [.env.example](.env.example). All application settings are defined in [config.py](src/doc_wiki/config.py).

| Setting | Default |
|---|---|
| `DOCWIKI_DATA_DIR` | `data` |
| `DOCWIKI_PROVIDER_CONCURRENCY` | `4` |
| `DOCWIKI_PROVIDER_TIMEOUT` | `30` seconds |
| `DOCWIKI_EXTRACTION_TIMEOUT` | `90` seconds |
| `DOCWIKI_REQUEST_TIMEOUT` | `180` seconds |
| `DOCWIKI_CONTEXT_NEIGHBORS` | `true` |
| `DOCWIKI_VISION_ENABLED` | `false` |
| `DOCWIKI_CONTEXTUAL_EMBEDDINGS` | `false` |
| `DOCWIKI_QUESTION_PLANNING` | `false` |

Default limits are 10 MiB per document, 256 KiB per questions file, 11 MiB per multipart request, 150 PDF pages, and 20 questions of up to 2,000 characters each. Narrative chunks target 700 tokens with 100-token overlap; retrieved evidence is capped at 6,000 tokens.

Optional vision, contextual embeddings, and question planning are experimental. Their quality and cost should be evaluated separately before enabling them. See [evaluation details](docs/evaluation.md).

## Testing

These checks use deterministic fake providers and do not require an API key:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/doc_wiki
uv run pytest -m "not live"
uv run python -m doc_wiki.eval --mode offline
```

Tests cover multipart requests, validation, extraction, retrieval, citation contracts, caching, deadlines, provider failures, and logging. Offline evaluation verifies application behavior; it does not measure OpenAI answer quality. Live semantic retesting of the grounding changes remains pending.

For a manual browser review with fake responses:

```bash
uv run python -m tests.browser_server
```

Open <http://127.0.0.1:8765>. The helper uses temporary storage. With Playwright and Chromium installed, run `node tests/browser-smoke.cjs` in another terminal for the browser smoke checks.

Live evaluation requires explicit approval, `DOCWIKI_LIVE_APPROVED=1`, and a sufficient budget argument. The estimate command makes no provider calls:

```bash
uv run python -m doc_wiki.eval --mode estimate --split dev
```

## Docker

```bash
docker build -t doc-wiki:local .
docker volume create doc-wiki-data
docker run --rm --name doc-wiki -p 127.0.0.1:8000:8000 \
  --env-file .env -v doc-wiki-data:/app/data doc-wiki:local
```

The container runs as UID 10001 with one Uvicorn process. Named volumes persist across restarts; host bind mounts must be writable by that UID. CI includes a container health smoke test. Local container execution has not yet been verified following an earlier environment disk-space failure.

Original uploads, extraction artifacts, and indexes remain in the configured data directory. To delete app-managed data, stop the server first, then run:

```bash
uv run python -m doc_wiki.reset --yes
```

## Project structure

```text
doc-wiki/
├── src/doc_wiki/
│   ├── app.py             # API routes and application lifecycle
│   ├── contracts.py       # Request, answer, and citation models
│   ├── service.py         # Ingestion and batch-answer orchestration
│   ├── pdf.py             # Isolated PDF extraction entry point
│   ├── json_source.py     # JSON parsing and source locations
│   ├── nodes.py           # Chunking and evidence metadata
│   ├── retrieval.py       # Persistent indexing and retrieval
│   ├── providers.py       # OpenAI calls and provider controls
│   ├── config.py          # Environment-backed settings
│   ├── eval.py            # Offline and gated live evaluation
│   └── static/            # Browser interface
├── tests/                 # Offline tests and browser smoke checks
├── examples/              # Runnable document and question examples
├── evaluation/            # Authored fixtures and evaluation cases
├── docs/                  # Architecture, evaluation, and review evidence
├── AGENTS.md              # Guidance for coding agents
├── .env.example
├── Dockerfile
├── pyproject.toml
└── uv.lock
```

## Review notes and limitations

Start with [architecture](docs/architecture.md), [evaluation observations](docs/evaluation.md), and the [review evidence matrix](docs/evidence.md) for implementation details and known gaps.

This application is intended for local assessment and demonstration. Production deployment would require authentication and authorization, quotas, retention and recovery policies, and deployment hardening. Document IDs are not access controls. Storage is local, has no automatic eviction, and permits one process per directory.

Logs omit document content, questions, answers, uploaded filenames, and credentials. `.env`, uploaded data, and private assessment materials are excluded from Git.

No project license has been selected. See [dependency licensing and redistribution](docs/licenses.md), including the PyMuPDF licensing considerations.
