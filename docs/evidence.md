# Rubric evidence matrix

This matrix reports evidence and limitations, without awarding points. The original Performance & Concurrency rubric ends after “and”; its missing remainder has not been invented.

| Category | Implementation / verification | Observed result | Remaining limitation |
|---|---|---|---|
| Backend correctness (15) | `app.py`, `contracts.py`, `service.py`; `tests/test_api.py`; real JSON and PDF multipart requests | Both formats, ordered duplicates, reuse, all four result statuses, invalid-citation errors, and HTTP 200 for all-failed answering batches tested | Live model output quality pending |
| Error handling & robustness (15) | Upload bounds; JSON depth/node/expansion limits; corrupt/encrypted/empty/page-limited PDFs; `test_pdf_failures.py`, `test_resilience.py`, `test_regressions.py` | Safe errors, deadline result preservation, parser termination/reaping/temp cleanup, partial coverage, and blank-key startup tested | No OCR; unusual layouts and abrupt-process crash remnants need manual review/reset |
| Code quality & structure (15) | Explicit extraction/retrieval/provider modules, typed contracts; Ruff, mypy, two-axis review | Lint, formatting, source type checks passed; four review findings resolved | Small assessment design; no general process supervisor or multi-process coordination |
| Tests (15) | `uv run pytest -m "not live"`; actual LlamaIndex/Chroma and deterministic fake providers; socket guard blocks network | 41 offline tests passed; browser smoke also passed | No paid model tests; offline fake responses cannot establish grounding quality |
| Performance & concurrency (15) | Global provider gate, async SDK, batched ingestion embeddings, unique-question reuse, keyed ingestion locks, store executor, subprocess parser | Event-controlled concurrency/health/deadline tests; restart and concurrent-upload reuse verified | Single API process; no production load test or storage hard-kill deadline |
| Containerization & observability (10) | Multi-stage non-root `Dockerfile`, named persistent volume, healthcheck, structured safe logs, offline CI | Frozen sync and fresh non-editable package installation passed, including packaged static/tokenizer assets and PDF QA; logging/model/usage path exercised with mocked SDK | Local Docker build attempted but daemon unavailable at Colima socket; container smoke pending; CI authored but no remote run |
| Grounding & answer quality (10) | LlamaIndex dense retrieval; untrusted-evidence prompt; schema and source-ID checks; 18 reviewed source cases | 14/14 required text/table evidence extracted; fake hit@6 9/14; structural citation validation passed; figure gate recorded | Semantic citation support, OpenAI retrieval quality, factual correctness and abstention require approved live calls plus human review |
| Minimal frontend (5) | `static/`; `tests/browser-smoke.cjs` with explicit fake-provider test server | Real headless Chrome: uploads, readiness/reuse, single/batch answers, errors/loading, ordered duplicates, citations, export, safe text, desktop/mobile layout | No conversational memory; no inline PDF page viewer |

## Verification record

Executed locally on Python 3.12.14:

```text
uv sync --frozen --group dev            PASS
fresh non-editable install + PDF QA    PASS (Python 3.12.12, temporary environment)
ruff check .                          PASS
ruff format --check .                 PASS
mypy src/docwiki                      PASS
pytest -m "not live"                   41 passed
python -m docwiki.eval --mode offline  18 cases, 0 skipped, no paid calls
node tests/browser-smoke.cjs           PASS using installed Chrome / fake server
docker build -t docwiki:local .        BLOCKED: local Docker daemon unavailable
```

Browser screenshots are local ignored artifacts. Committed [offline-results.json](offline-results.json) records the final diagnostic run; [evaluation.md](evaluation.md) explains its denominators and limits. The dependency and supplied-source review is in [licenses.md](licenses.md). The Git root is this `docWiki` directory and the branch is `feature/doc-wiki-with-rag`; no remote repository was created or pushed.
