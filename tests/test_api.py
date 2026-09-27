import asyncio
import json
import sys

import httpx
import pytest
import starlette.formparsers

from docwiki.app import create_app
from docwiki.config import Settings
from docwiki.contracts import ErrorResponse, ModelAnswer
from docwiki.errors import AppError
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
    repeated = await http.post("/api/qa", files=files)
    assert repeated.status_code == 200
    assert repeated.json()["document_id"] == data["document_id"]
    assert provider.embedding_calls == calls + 1
    assert provider.answer_calls == 2
    assert repeated.json()["results"] == data["results"]


async def test_public_schema_and_removed_document_routes(client):
    http, provider, _ = client
    schema = (await http.get("/openapi.json")).json()
    assert set(schema["paths"]) == {"/api/qa", "/healthz"}
    operation = schema["paths"]["/api/qa"]["post"]
    upload = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert set(upload["required"]) == {"document_file", "questions_file"}
    assert all(field["format"] == "binary" for field in upload["properties"].values())
    assert set(operation["responses"]) == {
        "200",
        "400",
        "413",
        "415",
        "422",
        "500",
        "502",
        "503",
        "504",
    }
    for status, response in operation["responses"].items():
        if status != "200":
            assert response["content"]["application/json"]["schema"]["$ref"].endswith(
                "/ErrorResponse"
            )
            assert "error" in response["content"]["application/json"]["example"]
    assert (await http.get("/docs")).status_code == 200
    assert (await http.post("/api/documents")).status_code == 404
    assert (await http.post("/api/documents/doc_test/questions")).status_code == 404
    assert provider.embedding_calls == provider.answer_calls == 0


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


async def test_malformed_questions_json_is_a_bad_request_before_paid_work(client):
    http, provider, _ = client
    response = await http.post(
        "/api/qa",
        files={
            "document_file": ("source.json", b'{"cloud":"ExampleCloud"}', "application/json"),
            "questions_file": ("questions.json", b'["unfinished"', "application/json"),
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert provider.embedding_calls == provider.answer_calls == 0


@pytest.mark.parametrize(
    "field,upload,status",
    [
        ("document_file", ("source.txt", b"text", "text/plain"), 415),
        ("document_file", ("source.xlsx", b"workbook", "application/octet-stream"), 415),
        ("questions_file", ("questions.pdf", b"%PDF-test", "application/pdf"), 415),
        ("document_file", ("source.pdf", b"not a PDF", "application/pdf"), 422),
        ("document_file", ("source.json", b"{broken", "application/json"), 422),
        ("document_file", ("source.json", b"", "application/json"), 422),
        ("questions_file", ("questions.json", b"\xff", "application/json"), 400),
        ("questions_file", ("questions.json", b'{"unexpected":[]}', "application/json"), 422),
    ],
)
async def test_rejected_files_return_documented_errors_without_provider_work(
    client, field, upload, status
):
    http, provider, _ = client
    files = {
        "document_file": ("source.json", b'{"cloud":"ExampleCloud"}', "application/json"),
        "questions_file": ("q.json", b'["Cloud?"]', "application/json"),
    }
    files[field] = upload
    response = await http.post("/api/qa", files=files)
    assert response.status_code == status, response.text
    error = ErrorResponse.model_validate(response.json())
    assert error.request_id == response.headers["x-request-id"]
    assert provider.embedding_calls == provider.answer_calls == 0


@pytest.mark.parametrize("case", ["missing", "duplicate", "extra", "text_field"])
async def test_incorrect_multipart_fields_are_validation_errors(client, case):
    http, provider, _ = client
    document = ("document_file", ("source.json", b'{"cloud":"ExampleCloud"}', "application/json"))
    questions = ("questions_file", ("q.json", b'["Cloud?"]', "application/json"))
    files = {
        "missing": [document],
        "duplicate": [document, document],
        "extra": [document, questions, ("extra", ("x.json", b"{}", "application/json"))],
        "text_field": [document, ("questions_file", (None, '["Cloud?"]'))],
    }[case]
    response = await http.post("/api/qa", files=files)
    assert response.status_code == 422
    assert ErrorResponse.model_validate(response.json()).error.code == "invalid_upload"
    assert provider.embedding_calls == provider.answer_calls == 0


@pytest.mark.parametrize(
    "content_type,body",
    [
        ("application/json", b"{}"),
        ("multipart/form-data", b"missing boundary"),
        ("multipart/form-data; boundary=expected", b"this is not multipart"),
    ],
)
async def test_malformed_multipart_returns_400(client, content_type, body):
    http, provider, _ = client
    response = await http.post("/api/qa", headers={"content-type": content_type}, content=body)
    assert response.status_code == 400
    assert ErrorResponse.model_validate(response.json()).error.code == "invalid_upload"
    assert provider.embedding_calls == provider.answer_calls == 0


@pytest.mark.parametrize("ending", [b"", b"\r\n--test\r\n"])
async def test_incomplete_multipart_is_rejected_before_provider_work(client, ending, monkeypatch):
    http, provider, _ = client
    temporary_files = []
    create_file = starlette.formparsers.SpooledTemporaryFile

    def tracked_file(*args, **kwargs):
        file = create_file(*args, **kwargs)
        temporary_files.append(file)
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked_file)
    body = (
        b'--test\r\nContent-Disposition: form-data; name="document_file"; '
        b'filename="source.json"\r\nContent-Type: application/json\r\n\r\n'
        b'{"cloud":"ExampleCloud"}\r\n'
        b'--test\r\nContent-Disposition: form-data; name="questions_file"; '
        b'filename="questions.json"\r\nContent-Type: application/json\r\n\r\n'
        b'["Cloud?"]' + ending
    )
    response = await http.post(
        "/api/qa", headers={"content-type": "multipart/form-data; boundary=test"}, content=body
    )
    assert response.status_code == 400
    assert ErrorResponse.model_validate(response.json()).error.code == "invalid_upload"
    assert provider.embedding_calls == provider.answer_calls == 0
    assert len(temporary_files) == 2
    assert all(file.closed for file in temporary_files)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_ingestion_failures_match_documented_error_envelope(client, status):
    http, provider, _ = client

    async def fail(texts):
        if status == 500:
            raise RuntimeError("PRIVATE exception contents")
        raise AppError("provider_failure", "Provider could not complete ingestion.", status)

    provider.embed = fail
    response = await http.post(
        "/api/qa",
        files={
            "document_file": ("source.json", b'{"cloud":"ExampleCloud"}', "application/json"),
            "questions_file": ("q.json", b'["Cloud?"]', "application/json"),
        },
    )
    assert response.status_code == status
    error = ErrorResponse.model_validate(response.json())
    assert error.request_id == response.headers["x-request-id"]
    assert "PRIVATE" not in response.text


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
                "/api/qa",
                files={
                    "document_file": (
                        "source.json",
                        b'{"cloud":"ExampleCloud"}',
                        "application/json",
                    ),
                    "questions_file": ("q.json", b'["invalid"]', "application/json"),
                },
            )
            assert failed.status_code == 200
            assert failed.json()["batch_status"] == "failed"
