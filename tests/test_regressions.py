import asyncio
import json
import sys
import threading
import time

import httpx
import pytest

from docwiki.app import create_app
from docwiki.config import Settings
from docwiki.contracts import Question
from docwiki.errors import AppError
from docwiki.json_source import extract_json
from docwiki.pdf import PDFExtractor
from docwiki.service import QAService
from tests.fakes import FakeProvider


def test_json_overflow_and_expansion_are_rejected():
    with pytest.raises(AppError, match="finite"):
        extract_json(b'{"number":1e999}', Settings())
    raw = json.dumps({f"field-{i}": i for i in range(1000)}).encode()
    with pytest.raises(AppError, match="configured limit"):
        extract_json(raw, Settings(extracted_bytes=4000))


async def test_one_row_continuation_is_never_discarded(tmp_path):
    path = tmp_path / "continuation.pdf"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "tests/make_continuation.py", str(path)
    )
    assert await process.wait() == 0
    result = await PDFExtractor(Settings()).extract(path)
    tables = [b for b in result.blocks if b.method == "pymupdf-table"]
    assert tables and ["CC42", "Annual review"] in tables[0].rows
    assert tables[0].location.page == 1
    assert ["Firewall", "Enabled"] in tables[1].rows
    assert ["Backups", "Daily"] in tables[1].rows
    assert tables[1].header == ["Column 1", "Column 2"]


async def test_blank_example_key_leaves_health_available_and_provider_unconfigured(tmp_path):
    settings = Settings(data_dir=tmp_path, OPENAI_API_KEY=" ")
    assert settings.openai_api_key is None
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/healthz")).status_code == 200
            response = await client.post(
                "/api/qa",
                files={
                    "document_file": (
                        "source.json",
                        b'{"cloud":"ExampleCloud"}',
                        "application/json",
                    ),
                    "questions_file": ("q.json", b'["Cloud?"]', "application/json"),
                },
            )
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "provider_unconfigured"


async def test_slow_store_read_cannot_erase_completed_batch_answer(tmp_path):
    app = create_app(
        Settings(data_dir=tmp_path, embedding_dimensions=64, request_timeout=0.4), FakeProvider()
    )
    release = threading.Event()
    async with app.router.lifespan_context(app):
        service = app.state.service
        await service.ingest(b'{"cloud":"ExampleCloud"}', "json")
        retrieve = service.store.retrieve

        def controlled(doc_id, question, embedding):
            if question == "slow":
                release.wait(3)
            return retrieve(doc_id, question, embedding)

        service.store.retrieve = controlled
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/qa",
                    files={
                        "document_file": (
                            "source.json",
                            b'{"cloud":"ExampleCloud"}',
                            "application/json",
                        ),
                        "questions_file": ("q.json", b'["cloud","slow"]', "application/json"),
                    },
                )
                assert response.status_code == 200, response.text
                assert [r["status"] for r in response.json()["results"]] == ["answered", "error"]
                assert not release.is_set()
        finally:
            release.set()


async def test_expired_answering_deadline_after_ready_ingestion_returns_results(tmp_path):
    provider = FakeProvider()
    service = QAService(Settings(data_dir=tmp_path, embedding_dimensions=64), provider)
    await service.start()
    try:
        document = await service.ingest(b'{"cloud":"ExampleCloud"}', "json")
        embedding_calls = provider.embedding_calls

        def no_redundant_lookup(*args):
            raise AssertionError("Readiness was already established by ingestion")

        service.store.ready = no_redundant_lookup
        result = await service.questions(
            document.document_id,
            [Question(id="q", question="Cloud?")],
            time.monotonic() - 1,
            ready_document=document,
        )
        assert result.batch_status == "failed"
        assert result.results[0].error.code == "request_timeout"
        assert provider.embedding_calls == embedding_calls
    finally:
        await service.close()
