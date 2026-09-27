# Rubric evidence matrix

This matrix reports evidence and limitations, without awarding points. The original Performance & Concurrency rubric ends after “and”; its missing remainder has not been invented.

| Category | Implementation / verification | Observed result | Remaining limitation |
|---|---|---|---|
| Backend correctness (15) | `app.py`, `contracts.py`, `service.py`; `tests/test_api.py`; real JSON and PDF multipart requests | One `/api/qa` workflow requires both files; both formats, ordered duplicates, reuse, all four result statuses, invalid-citation errors, and HTTP 200 for all-failed answering batches tested; removed routes return 404 | 19-case baseline reviewed; post-change live quality pending |
| Error handling & robustness (15) | Upload bounds; JSON depth/node/expansion limits; corrupt/encrypted/empty/page-limited PDFs; `test_api.py`, `test_pdf_failures.py`, `test_resilience.py`, `test_regressions.py` | Typed error schemas and 400/413/415/422 responses verified without provider calls; safe ingestion failures, deadline result preservation, parser termination/reaping/temp cleanup, partial coverage, and blank-key startup tested | No OCR; unusual layouts and abrupt-process crash remnants need manual review/reset |
| Code quality & structure (15) | Explicit extraction/retrieval/provider modules, typed contracts; Ruff, mypy, two-axis review | Lint, formatting, source type checks passed; four review findings resolved | Small assessment design; no general process supervisor or multi-process coordination |
| Tests (15) | `uv run pytest -m "not live"`; actual LlamaIndex/Chroma and deterministic fake providers; socket guard blocks network | 111 offline tests passed; browser smoke also passed | One approved 19-question baseline; no post-change paid retest; fake responses cannot establish grounding quality |
| Performance & concurrency (15) | Global provider gate, async SDK, batched ingestion embeddings, unique-question reuse, keyed ingestion locks, store executor, subprocess parser | Event-controlled concurrency/health/deadline tests; restart and concurrent-upload reuse verified | Single API process; no production load test or storage hard-kill deadline |
| Containerization & observability (10) | Multi-stage non-root `Dockerfile`, named persistent volume, healthcheck, structured safe logs, offline CI; `test_observability.py` | Frozen sync and fresh non-editable package installation passed; JSON request IDs/status/latency, ingestion/cache, provider/model/retries/latency/token usage and exclusion of credentials, filenames, source text, questions and answers verified with mocked SDK | Local Docker build attempted but daemon unavailable at Colima socket; container smoke pending; CI authored but no remote run |
| Grounding & answer quality (10) | LlamaIndex dense retrieval; scoped evidence prompt; server citation allowlisting; 18 original cases, 19 workbook development cases, 24 authored contract scenarios | Original fake hit@6 9/14; workbook live hit@6 8/8 but complete evidence 1/8; 14/22 required groups retrieved, 22/22 extracted; specific abstention and related-citation contracts verified | Workbook baseline reviewed separately: status agreement 11/19 and clear overclaims; post-change semantic quality remains unmeasured |
| Minimal frontend (5) | `static/`; `tests/browser-smoke.cjs` with explicit fake-provider test server | Real headless Chrome: centered two-file form, one QA request per submission, all four statuses, errors/loading, ordered duplicates, citations, warnings, export, safe text, distinct related facts with separate citations, omission/export, stale-state clearing, desktop/mobile layout and Swagger file controls | No conversational memory; no inline PDF page viewer |

## Verification record

Executed locally on Python 3.12.14:

```text
uv sync --frozen --group dev            PASS
fresh non-editable install + PDF QA    PASS (Python 3.12.12, temporary environment)
ruff check .                          PASS
ruff format --check .                 PASS
mypy src/docwiki                      PASS
pytest -m "not live"                   111 passed
python -m docwiki.eval --mode offline  18 cases, 0 skipped, no paid calls
node tests/browser-smoke.cjs           PASS using installed Chrome / fake server
docker build -t docwiki:local .        BLOCKED: local Docker daemon unavailable
```

Browser screenshots are local ignored artifacts. Committed [offline-results.json](offline-results.json) records the final diagnostic run; [evaluation.md](evaluation.md) explains its denominators and limits. The dependency and supplied-source review is in [licenses.md](licenses.md). The Git root is this `docWiki` directory and the branch is `feature/doc-wiki-with-rag`; no remote repository was created or pushed.

The [workbook review](workbook-review.md) separates actual baseline findings, unsupported reference claims and pending semantic retests. The full local 19-row HTML/JSON report contains original answers and ranked evidence; it stays out of Git and Docker. The approved baseline cost estimate from reported usage was $0.006732. No post-change paid calls or storage reset occurred.
