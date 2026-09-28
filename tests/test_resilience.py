import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

from doc_wiki.app import create_app
from doc_wiki.config import Settings
from doc_wiki.contracts import Evidence, Location, ModelAnswer, Question
from doc_wiki.errors import AppError
from doc_wiki.pdf import PDFExtractor
from doc_wiki.service import QAService, validate_answer
from tests.fakes import FakeProvider


@pytest.mark.parametrize(
    "status,ids,valid",
    [
        ("answered", ["good"], True),
        ("partial", ["good"], True),
        ("not_found", [], True),
        ("answered", ["invented"], False),
        ("answered", [], False),
        ("not_found", ["good"], False),
    ],
)
def test_status_and_citation_contract(status, ids, valid):
    evidence = [
        Evidence(
            source_id="good",
            text="Only this source text.",
            kind="json",
            location=Location(json_path="$[0]"),
            method="json-record",
        )
    ]
    answer = ModelAnswer(
        answer="Supported portion; the rest is undocumented.", status=status, source_ids=ids
    )
    question = Question(id="1", question="Question?")
    if valid:
        result = validate_answer(question, answer, evidence)
        assert result.status == status
        if ids:
            assert result.citations[0].excerpt == evidence[0].text
    else:
        with pytest.raises(AppError, match="validation"):
            validate_answer(question, answer, evidence)


async def test_cache_restart_concurrent_ingestion_and_config_invalidation(tmp_path):
    provider = FakeProvider()
    settings = Settings(data_dir=tmp_path / "data", embedding_dimensions=64)
    raw = b'{"cloud":"ExampleCloud"}'
    service = QAService(settings, provider)
    await service.start()
    first, second = await asyncio.gather(service.ingest(raw, "json"), service.ingest(raw, "json"))
    assert first.document_id == second.document_id
    assert first.cache_hit != second.cache_hit
    assert provider.embedding_calls == 1
    await service.close()
    restarted = QAService(settings, provider)
    await restarted.start()
    try:
        assert (await restarted.ingest(raw, "json")).cache_hit
        assert provider.embedding_calls == 1
        changed = QAService(settings.model_copy(update={"chunk_tokens": 500}), provider)
        assert changed.store.document_id(raw) != first.document_id
        await changed.store.close()
    finally:
        await restarted.close()


async def test_question_failure_and_deadline_preserve_completed_results(tmp_path):
    class Controlled(FakeProvider):
        async def answer(self, question, evidence, warnings):
            if question == "slow":
                await asyncio.Event().wait()
            if question == "broken":
                raise AppError("provider_auth", "Provider authentication failed.", 503)
            return await super().answer(question, evidence, warnings)

    service = QAService(Settings(data_dir=tmp_path, embedding_dimensions=64), Controlled())
    await service.start()
    try:
        doc = await service.ingest(b'{"cloud":"ExampleCloud"}', "json")
        questions = [
            Question(id=str(i), question=q)
            for i, q in enumerate(["cloud", "slow", "broken", "cloud"])
        ]
        result = await service.questions(doc.document_id, questions, time.monotonic() + 0.3)
        assert [r.status for r in result.results] == ["answered", "error", "error", "answered"]
        assert result.results[1].error.code == "request_timeout"
        assert result.results[2].error.code == "provider_auth"
        assert result.batch_status == "partial_failure"
        result = await service.questions(doc.document_id, [questions[2]], time.monotonic() + 1)
        assert result.batch_status == "failed"
    finally:
        await service.close()


async def test_pdf_timeout_reaps_worker_cleans_temp_and_releases_slot(tmp_path):
    settings = Settings(extraction_timeout=0.3)
    worker = PDFExtractor(settings, [sys.executable, "tests/slow_pdf.py"])
    path = tmp_path / "slow.pdf"
    path.write_bytes(b"%PDF-test")
    with pytest.raises(AppError, match="timed out"):
        await worker.extract(path)
    pid = int(Path(str(path) + ".pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not Path(Path(str(path) + ".output").read_text()).parent.exists()
    assert (await worker.extract(tmp_path / "fast.pdf")).page_count == 1


async def test_health_responsive_while_extraction_is_waiting(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class ControlledPDF:
        async def extract(self, path):
            entered.set()
            await release.wait()
            raise AppError("invalid_pdf", "Synthetic failure.")

    settings = Settings(data_dir=tmp_path, embedding_dimensions=64)
    app = create_app(settings, FakeProvider())
    async with app.router.lifespan_context(app):
        app.state.service.pdf = ControlledPDF()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ingest = asyncio.create_task(
                client.post(
                    "/api/qa",
                    files={
                        "document_file": ("x.pdf", b"%PDF-test", "application/pdf"),
                        "questions_file": ("q.json", b'["Cloud?"]', "application/json"),
                    },
                )
            )
            await asyncio.wait_for(entered.wait(), 2)
            assert (await client.get("/healthz")).status_code == 200
            assert not ingest.done()
            release.set()
            assert (await ingest).status_code == 422
            assert list((tmp_path / "documents").iterdir()) == []


async def test_body_and_part_limits_before_paid_work(tmp_path):
    provider = FakeProvider()
    settings = Settings(
        data_dir=tmp_path,
        embedding_dimensions=64,
        body_bytes=1024,
        questions_bytes=16,
        document_bytes=128,
    )
    app = create_app(settings, provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/qa",
                files={
                    "document_file": ("x.json", b'{"a":"' + b"x" * 200 + b'"}', "application/json"),
                    "questions_file": ("q.json", b'["Cloud?"]', "application/json"),
                },
            )
            assert response.status_code == 413
            response = await client.post(
                "/api/qa",
                files={
                    "document_file": ("x.json", b'{"a":1}', "application/json"),
                    "questions_file": (
                        "q.json",
                        b'["long question beyond limit"]',
                        "application/json",
                    ),
                },
            )
            assert response.status_code == 413
            boundary = (
                b'--hello\r\nContent-Disposition: form-data; name="document_file"; '
                b'filename="x.json"\r\nContent-Type: application/json\r\n\r\n'
            )

            async def stream():
                yield boundary
                yield b"x" * 1500
                yield b"\r\n--hello--\r\n"

            response = await client.post(
                "/api/qa",
                content=stream(),
                headers={"content-type": "multipart/form-data; boundary=hello"},
            )
            assert response.status_code == 413
            assert provider.embedding_calls == 0
