import asyncio
import json
import sys

import httpx
import pytest

from docwiki.app import create_app
from docwiki.config import Settings
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
