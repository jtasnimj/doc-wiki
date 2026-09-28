import io
import json
import logging

import httpx
import openai

from doc_wiki.app import create_app
from doc_wiki.config import Settings
from doc_wiki.observability import JSONFormatter, logger
from doc_wiki.providers import OpenAIProvider


async def test_json_logs_capture_request_cache_provider_usage_without_sensitive_content(tmp_path):
    def transport(request):
        payload = json.loads(request.content)
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"index": i, "object": "embedding", "embedding": [1.0] * 64}
                        for i in range(len(payload["input"]))
                    ],
                    "model": "text-embedding-3-small",
                    "usage": {"prompt_tokens": 3, "total_tokens": 3},
                },
            )
        evidence = json.loads(payload["input"][1]["content"][0]["text"])["evidence"]
        result = {
            "result": {
                "outcome": "answered",
                "claims": [
                    {
                        "text": "PRIVATE_ANSWER",
                        "source_ids": [evidence[0]["source_id"]],
                        "question_part_ids": ["q1"],
                    }
                ],
            }
        }
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "gpt-4o-mini",
                "usage": {
                    "input_tokens": 30,
                    "output_tokens": 6,
                    "total_tokens": 36,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": json.dumps(result), "annotations": []}
                        ],
                    }
                ],
            },
        )

    settings = Settings(data_dir=tmp_path, embedding_dimensions=64, OPENAI_API_KEY=None)
    sdk = openai.AsyncOpenAI(
        api_key="PRIVATE_API_KEY",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    app = create_app(settings, OpenAIProvider(settings, sdk))
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    async with app.router.lifespan_context(app):
        logger.addHandler(handler)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                files = {
                    "document_file": (
                        "PRIVATE_FILENAME.json",
                        b'{"cloud":"PRIVATE_DOCUMENT"}',
                        "application/json",
                    ),
                    "questions_file": (
                        "questions.json",
                        b'["PRIVATE_QUESTION"]',
                        "application/json",
                    ),
                }
                first = await client.post("/api/qa", files=files)
                repeated = await client.post("/api/qa", files=files)
                assert first.status_code == repeated.status_code == 200
                assert first.json()["results"][0]["answer"] == "PRIVATE_ANSWER"
                files["questions_file"] = ("questions.json", b"[", "application/json")
                invalid = await client.post("/api/qa", files=files)
                assert invalid.status_code == 400
        finally:
            logger.removeHandler(handler)
            handler.close()

    output = stream.getvalue()
    assert "PRIVATE_" not in output
    events = [json.loads(line) for line in output.splitlines()]
    ids = {r.headers["x-request-id"] for r in [first, repeated, invalid]}
    assert all(event["request_id"] in ids for event in events)
    assert all(event["timestamp"] and event["level"] for event in events)
    requests = [event for event in events if event["event"] == "request_complete"]
    assert [event["status"] for event in requests] == [200, 200, 400]
    assert all(event["latency_ms"] >= 0 for event in requests)
    ingestion = [event for event in events if event["event"] == "ingestion"]
    assert [event["index_cache_hit"] for event in ingestion] == [False, True]
    assert all(event["document_id"] == first.json()["document_id"] for event in ingestion)
    assert ingestion[0]["latency_ms"] >= 0 and ingestion[0]["chunk_count"] > 0
    retrieval = [event for event in events if event["event"] == "retrieval_complete"]
    assert len(retrieval) == 2
    assert all(event["seed_count"] == 1 and event["context_count"] == 0 for event in retrieval)
    assert all(0 < event["evidence_tokens"] <= settings.evidence_tokens for event in retrieval)
    assert all(event["latency_ms"] >= 0 for event in retrieval)
    providers = [event for event in events if event["event"] == "provider_complete"]
    assert {event["model"] for event in providers} == {"gpt-4o-mini", "text-embedding-3-small"}
    assert all(event["provider"] == "openai" and event["retries"] == 0 for event in providers)
    assert all(
        event["latency_ms"] >= 0 and event["usage"]["total_tokens"] > 0 for event in providers
    )
    assert any(
        event["event"] == "request_error" and event["error_category"] == "invalid_json"
        for event in events
    )
