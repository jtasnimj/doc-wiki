import asyncio
import json
import time

import httpx
import openai
import pytest

from docwiki.app import create_app
from docwiki.config import Settings
from docwiki.contracts import Question
from docwiki.errors import AppError
from docwiki.grounding import PlanEnvelope, compile_question_plan
from docwiki.providers import OpenAIProvider
from docwiki.service import QAService
from tests.fakes import FakeProvider
from tests.test_answer_contract import sdk_response


async def test_question_plan_sees_only_original_question_and_preserves_all_spans():
    question = "Are alerts logged, and are archived logs retained for 21 days?"
    requests = []

    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return sdk_response(
            {
                "segments": ["Are alerts logged, ", "and are archived logs retained for 21 days?"],
                "parts": [{"segment_ids": [1]}, {"segment_ids": [2]}],
                "shared_segment_ids": [],
            }
        )

    sdk = openai.AsyncOpenAI(
        api_key="offline-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    provider = OpenAIProvider(Settings(question_planning=True), sdk)
    try:
        plan = await provider.plan(question)
        assert plan.original == question
        assert plan.parts[1].spans == ["and are archived logs retained for 21 days?"]
        assert [p.id for p in plan.parts] == ["q1", "q2"]
        assert len(requests) == 1
        assert json.loads(requests[0]["input"][1]["content"]) == {"question": question}
    finally:
        await provider.close()


@pytest.mark.parametrize("change", ["rewrite", "omit", "reference", "unused", "overlap"])
def test_invalid_question_plan_cannot_drop_qualifiers_or_invent_references(change):
    question = "Does the policy cover regulated systems?"
    draft = {
        "segments": ["Does the policy cover ", "regulated systems?"],
        "parts": [{"segment_ids": [1, 2]}],
        "shared_segment_ids": [],
    }
    if change == "rewrite":
        draft["segments"][1] = "systems?"
    if change == "omit":
        draft["segments"].pop()
    if change == "reference":
        draft["parts"][0]["segment_ids"] = [1, 9]
    if change == "unused":
        draft["parts"][0]["segment_ids"] = [1]
    if change == "overlap":
        draft["parts"].append({"segment_ids": [2]})
    with pytest.raises(AppError) as error:
        compile_question_plan(question, PlanEnvelope.model_validate(draft))
    assert error.value.code == "invalid_model_output"


def test_shared_scope_applies_to_all_parts_and_alternatives_can_stay_whole():
    question = "For the archive, are events logged and alerts sent?"
    plan = compile_question_plan(
        question,
        PlanEnvelope.model_validate(
            {
                "segments": ["For the archive, ", "are events logged ", "and alerts sent?"],
                "parts": [{"segment_ids": [2]}, {"segment_ids": [3]}],
                "shared_segment_ids": [1],
            }
        ),
    )
    assert plan.shared_scope == ["For the archive, "]
    assert plan.original == question
    alternative = "Must operators log events or notify the duty officer?"
    unsplit = compile_question_plan(
        alternative,
        PlanEnvelope.model_validate(
            {
                "segments": [alternative],
                "parts": [{"segment_ids": [1]}],
                "shared_segment_ids": [],
            }
        ),
    )
    assert unsplit.parts[0].spans == [alternative]


async def test_disabled_planning_makes_no_provider_call():
    provider = OpenAIProvider(Settings(OPENAI_API_KEY=None))
    try:
        assert (await provider.plan("Original question?")).original == "Original question?"
        assert provider.usage_records == []
    finally:
        await provider.close()


async def test_batch_reuses_question_planning_and_preserves_completed_results(tmp_path):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class ControlledProvider(FakeProvider):
        async def plan(self, question):
            if question == "slow":
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await super().plan(question)

    provider = ControlledProvider()
    service = QAService(
        Settings(data_dir=tmp_path, embedding_dimensions=64, question_planning=True), provider
    )
    await service.start()
    try:
        info = await service.ingest(b'{"cloud":"ExampleCloud"}', "json")
        result = await service.questions(
            info.document_id,
            [
                Question(id="first", question="Cloud?"),
                Question(id="copy", question="Cloud?"),
                Question(id="last", question="slow"),
            ],
            time.monotonic() + 0.3,
            ready_document=info,
        )
        assert entered.is_set() and cancelled.is_set()
        assert provider.plan_calls == provider.answer_calls == 1
        assert [r.id for r in result.results] == ["first", "copy", "last"]
        assert [r.status for r in result.results] == ["answered", "answered", "error"]
        assert result.results[-1].error.code == "request_timeout"
    finally:
        await service.close()


async def test_planning_and_embeddings_share_the_same_provider_gate():
    planning, embedding_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    operations = []

    async def transport(request):
        operations.append(request.url.path)
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [{"index": 0, "object": "embedding", "embedding": [1.0] * 64}],
                    "model": "text-embedding-3-small",
                },
            )
        planning.set()
        await release.wait()
        return sdk_response(
            {"segments": ["Question?"], "parts": [{"segment_ids": [1]}], "shared_segment_ids": []}
        )

    sdk = openai.AsyncOpenAI(
        api_key="offline-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    provider = OpenAIProvider(
        Settings(question_planning=True, provider_concurrency=1, embedding_dimensions=64), sdk
    )

    async def embed():
        embedding_started.set()
        return await provider.embed(["Question?"])

    task = asyncio.create_task(provider.plan("Question?"))
    try:
        await asyncio.wait_for(planning.wait(), 2)
        queued = asyncio.create_task(embed())
        await asyncio.wait_for(embedding_started.wait(), 2)
        assert len(operations) == 1
        assert not queued.done()
        release.set()
        await asyncio.gather(task, queued)
        assert len(operations) == 2 and operations[1].endswith("embeddings")
    finally:
        release.set()
        await provider.close()


async def test_health_is_responsive_during_question_planning(tmp_path):
    planning, release = asyncio.Event(), asyncio.Event()

    class ControlledProvider(FakeProvider):
        async def plan(self, question):
            planning.set()
            await release.wait()
            return await super().plan(question)

    app = create_app(
        Settings(data_dir=tmp_path, embedding_dimensions=64, question_planning=True),
        ControlledProvider(),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            task = asyncio.create_task(
                client.post(
                    "/api/qa",
                    files={
                        "document_file": ("source.json", b'{"cloud":"ExampleCloud"}'),
                        "questions_file": ("questions.json", b'["Cloud?"]'),
                    },
                )
            )
            try:
                await asyncio.wait_for(planning.wait(), 3)
                response = await asyncio.wait_for(client.get("/healthz"), 1)
                assert response.status_code == 200 and not task.done()
            finally:
                release.set()
                result = await task
            assert result.status_code == 200
            assert result.json()["results"][0]["status"] == "answered"
