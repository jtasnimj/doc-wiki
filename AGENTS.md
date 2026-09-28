# Working on doc-wiki

## Project conventions

- Use `doc-wiki` for the project, distribution, directory, and display name. Use `doc_wiki` for Python imports and the package under `src/`.
- Retain the existing `DOCWIKI_` environment prefix and persisted metadata keys unless a change explicitly includes a migration.
- Use Python 3.12 and uv with the committed lockfile. Keep dependency changes intentional and update `uv.lock` when necessary.
- Read `README.md` for setup and API behavior, `docs/architecture.md` for design, and `docs/evaluation.md` for evaluation limits.

## Implementation boundaries

- `app.py` owns HTTP handling; `service.py` orchestrates ingestion and answers; extraction, retrieval, and provider concerns live in their respective modules.
- Preserve question wording, IDs, ordering, typed outcomes, and citation provenance. Do not turn related information into an unsupported answer.
- Treat uploaded documents as untrusted data. Keep upload limits, provider deadlines, concurrency bounds, and storage locking intact.
- Keep real provider calls behind the provider interface. Use deterministic fakes for offline tests; do not add an implicit fake-provider mode to the application.
- Never expose API keys to the browser or log source content, questions, answers, filenames, or credentials.
- Do not commit `.env`, local data/indexes, private `instructions/`, or generated artifacts. Leave unrelated local changes untouched.

## Verification

Run checks appropriate to the change. For package renames or changes spanning the application, run:

```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src/doc_wiki
uv run pytest -m "not live"
uv run python -m doc_wiki.eval --mode offline
```

For browser changes, use `python -m tests.browser_server` through uv and the existing `tests/browser-smoke.cjs` workflow. For container changes, build the image and check `/healthz` when Docker is available.

Offline tests establish application behavior, not real-model answer quality. Live evaluation requires explicit authorization for the cases and cost, plus the evaluator's approval flag and budget guard. Do not call paid providers as a side effect of ordinary verification.

## Documentation

- Keep README commands, examples, CI, Docker entry points, and package paths consistent.
- Use authored fixtures for public examples. Label illustrative model responses and distinguish expected behavior from measured results.
- Report completed checks and any verification limits accurately. Do not describe the local demo as production-ready or claim unmeasured semantic quality.
