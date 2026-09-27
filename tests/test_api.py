import asyncio
import json
import sys

import httpx
import pytest

from docwiki.app import create_app
from docwiki.config import Settings
from docwiki.contracts import ModelAnswer
from tests.fakes import FakeProvider


@pytest.fixture
async def client(tmp_path):
    provider = FakeProvider()
    app = create_app(Settings(data_dir=tmp_path / "data", embedding_dimensions=64), provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, provider, app


async def test_two_file_json_workflow_and_ready_index_reuse(client):
    http, provider, app = client
    files = {
        "document_file": ("source.json", b'{"cloud":"ExampleCloud"}', "application/json"),
        "questions_file": ("questions.json", b'["Cloud?","Cloud?"]', "application/json"),
    }
    response = await http.post("/api/qa", files=files)
    assert response.status_code == 200, response.text
    data = response.json()
    assert [r["question"] for r in data["results"]] == ["Cloud?", "Cloud?"]
    assert all(r["answer"] == "ExampleCloud." for r in data["results"])
    assert provider.answer_calls == 1
    citation = data["results"][0]["citations"][0]
    assert citation["locations"][0]["json_path"] == "$"
    assert "ExampleCloud" in citation["excerpt"]
    calls = provider.embedding_calls
    repeated = await http.post("/api/documents", files={"document_file": files["document_file"]})
    assert repeated.json()["cache_hit"] is True
    assert provider.embedding_calls == calls
    response = await http.post(
        f"/api/documents/{data['document_id']}/questions", json={"questions": ["Cloud?"]}
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "answered"


async def test_pdf_multipart_retains_real_parsing_and_retrieval(client, tmp_path):
    http, provider, app = client
    path = tmp_path / "source.pdf"
    process = await asyncio.create_subprocess_exec(sys.executable, "tests/make_pdf.py", str(path))
    assert await process.wait() == 0
    response = await http.post(
        "/api/qa",
        files={
            "document_file": ("source.pdf", path.read_bytes(), "application/pdf"),
            "questions_file": ("questions.json", b'["Hosting provider?"]', "application/json"),
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "answered"
    assert result["citations"][0]["locations"][0]["page"] == 2


@pytest.mark.parametrize(
    "questions",
    [[], [""], ["q"] * 21, [{"id": "x", "question": "a"}, {"id": "x", "question": "b"}]],
)
async def test_invalid_questions_fail_before_any_provider_work(client, questions):
    http, provider, app = client
    response = await http.post(
        "/api/qa",
        files={
            "document_file": ("source.json", b'{"cloud":"ExampleCloud"}', "application/json"),
            "questions_file": (
                "questions.json",
                json.dumps(questions).encode(),
                "application/json",
            ),
        },
    )
    assert response.status_code == 422
    assert provider.embedding_calls == provider.answer_calls == 0


async def test_batch_statuses_invalid_citations_and_all_failed_still_http_200(tmp_path):
    class StatusProvider(FakeProvider):
        async def answer(self, question, evidence, warnings):
            if question == "partial":
                return ModelAnswer(
                    status="partial",
                    answer="ExampleCloud; region is not documented.",
                    source_ids=[evidence[0].source_id],
                )
            if question == "missing":
                return ModelAnswer(status="not_found", answer="Not found.", source_ids=[])
            if question == "invalid":
                return ModelAnswer(status="answered", answer="Fabricated.", source_ids=["forged"])
            return await super().answer(question, evidence, warnings)

    app = create_app(Settings(data_dir=tmp_path, embedding_dimensions=64), StatusProvider())
    async with app.router.lifespan_context(app):
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
                    "questions_file": (
                        "q.json",
                        b'["cloud","partial","missing","invalid"]',
                        "application/json",
                    ),
                },
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert [r["status"] for r in data["results"]] == [
                "answered",
                "partial",
                "not_found",
                "error",
            ]
            assert data["results"][2]["answer"] == "Not found in the provided document."
            assert data["results"][2]["citations"] == []
            assert data["results"][3]["answer"] is None
            assert data["results"][3]["error"]["code"] == "invalid_model_output"
            assert data["batch_status"] == "partial_failure"
            failed = await client.post(
                f"/api/documents/{data['document_id']}/questions", json={"questions": ["invalid"]}
            )
            assert failed.status_code == 200
            assert failed.json()["batch_status"] == "failed"
