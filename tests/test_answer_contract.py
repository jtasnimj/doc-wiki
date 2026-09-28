import json

import httpx
import openai
import pytest

from docwiki.config import Settings
from docwiki.contracts import Evidence, Location
from docwiki.errors import AppError
from docwiki.providers import OpenAIProvider


def sdk_response(result):
    return httpx.Response(
        200,
        json={
            "id": "resp_contract",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": "gpt-4o-mini",
            "output": [
                {
                    "id": "msg_contract",
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


def evidence():
    return [
        Evidence(
            source_id="source-a",
            text="The console does not lock accounts after failures.",
            kind="json",
            method="json-record",
            location=Location(json_path="$"),
        )
    ]


async def test_supported_negative_uses_typed_claims_with_the_complete_original_question():
    requests = []
    question = "Does the console lock accounts after seven failed attempts?"

    def transport(request):
        requests.append(json.loads(request.content))
        return sdk_response(
            {
                "result": {
                    "outcome": "answered",
                    "claims": [
                        {
                            "text": "No. The console does not lock accounts after failures.",
                            "source_ids": ["source-a"],
                            "question_part_ids": ["q1"],
                        }
                    ],
                }
            }
        )

    sdk = openai.AsyncOpenAI(
        api_key="offline-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    provider = OpenAIProvider(Settings(), sdk)
    try:
        result = await provider.answer(question, evidence(), [])
        assert result.status == "answered"
        assert result.answer.startswith("No.")
        assert result.source_ids == ["source-a"]
        assert len(requests) == 1
        payload = json.loads(requests[0]["input"][1]["content"][0]["text"])
        assert payload["question"] == question
        assert payload["question_plan"]["parts"][0]["spans"] == [question]
        schema = requests[0]["text"]["format"]["schema"]
        assert schema["type"] == "object" and "anyOf" not in schema
        assert "anyOf" in schema["properties"]["result"]
    finally:
        await provider.close()


async def test_partial_answer_preserves_supported_and_missing_parts():
    def transport(request):
        return sdk_response(
            {
                "result": {
                    "outcome": "partial",
                    "claims": [
                        {
                            "text": "Account lockout is disabled.",
                            "source_ids": ["source-a"],
                            "question_part_ids": ["q1"],
                        }
                    ],
                    "missing": [
                        {"text": "the session lifetime limit", "question_part_ids": ["q1"]}
                    ],
                }
            }
        )

    sdk = openai.AsyncOpenAI(
        api_key="offline-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    provider = OpenAIProvider(Settings(), sdk)
    try:
        result = await provider.answer(
            "Are accounts locked and sessions time-limited?", evidence(), []
        )
        assert result.status == "partial"
        assert "Account lockout is disabled." in result.answer
        assert "does not establish the session lifetime limit" in result.answer
        assert result.related_information == []
    finally:
        await provider.close()


@pytest.mark.parametrize("reverse", [False, True])
async def test_conflicting_source_statements_remain_partial_with_both_citations(reverse):
    def transport(request):
        return sdk_response(
            {
                "result": {
                    "outcome": "conflicting",
                    "alternatives": [
                        {
                            "text": "Accounts are not locked.",
                            "source_ids": ["source-a"],
                            "question_part_ids": ["q1"],
                        },
                        {
                            "text": "Accounts are locked.",
                            "source_ids": ["source-b"],
                            "question_part_ids": ["q1"],
                        },
                    ],
                }
            }
        )

    sdk = openai.AsyncOpenAI(
        api_key="offline-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    provider = OpenAIProvider(Settings(), sdk)
    sources = evidence() + [
        Evidence(
            source_id="source-b",
            text="Accounts are locked.",
            kind="json",
            method="json-record",
            location=Location(json_path="$[1]"),
        )
    ]
    if reverse:
        sources.reverse()
    try:
        result = await provider.answer("Are accounts locked?", sources, [])
        assert result.status == "partial"
        assert "conflicting statements" in result.answer
        assert result.source_ids == ["source-a", "source-b"]
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "result",
    [
        {"outcome": "answered", "claims": []},
        {
            "outcome": "answered",
            "claims": [{"text": "A claim.", "source_ids": [], "question_part_ids": ["q1"]}],
        },
        {
            "outcome": "answered",
            "claims": [
                {"text": "A claim.", "source_ids": ["foreign"], "question_part_ids": ["q1"]}
            ],
        },
        {
            "outcome": "answered",
            "claims": [
                {
                    "text": "A claim.",
                    "source_ids": ["source-a"],
                    "question_part_ids": ["other-question"],
                }
            ],
        },
        {
            "outcome": "answered",
            "claims": [
                {"text": "A claim.", "source_ids": ["source-a"], "question_part_ids": ["q1"]}
            ],
            "related_information": [],
        },
        {
            "outcome": "partial",
            "claims": [
                {"text": "A claim.", "source_ids": ["source-a"], "question_part_ids": ["q1"]}
            ],
            "missing": [],
        },
        {
            "outcome": "not_found",
            "missing": [{"text": "the threshold", "question_part_ids": ["q1"]}],
            "related_information": [{"text": "Background.", "source_ids": ["foreign"]}],
        },
        {
            "outcome": "not_found",
            "missing": [{"text": " ", "question_part_ids": ["q1"]}],
            "related_information": [],
        },
        {
            "outcome": "conflicting",
            "alternatives": [
                {"text": "Same statement.", "source_ids": ["source-a"], "question_part_ids": ["q1"]}
            ]
            * 2,
        },
    ],
)
async def test_invalid_answer_combinations_and_references_are_errors_without_repair(result):
    calls = []

    def transport(request):
        calls.append(request)
        return sdk_response({"result": result})

    sdk = openai.AsyncOpenAI(
        api_key="offline-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    provider = OpenAIProvider(Settings(), sdk)
    try:
        with pytest.raises(AppError) as error:
            await provider.answer("Question?", evidence(), [])
        assert error.value.code == "invalid_model_output"
        assert len(calls) == 1
    finally:
        await provider.close()


async def test_answer_must_account_for_every_part_of_a_validated_question_plan():
    from docwiki.grounding import PlanEnvelope, compile_question_plan

    question = "Are alarms logged and retained for 21 days?"
    plan = compile_question_plan(
        question,
        PlanEnvelope.model_validate(
            {
                "segments": ["Are alarms logged ", "and retained for 21 days?"],
                "parts": [{"segment_ids": [1]}, {"segment_ids": [2]}],
                "shared_segment_ids": [],
            }
        ),
    )

    def transport(request):
        return sdk_response(
            {
                "result": {
                    "outcome": "answered",
                    "claims": [
                        {
                            "text": "Alarms are logged.",
                            "source_ids": ["source-a"],
                            "question_part_ids": ["q1"],
                        }
                    ],
                }
            }
        )

    sdk = openai.AsyncOpenAI(
        api_key="offline-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    provider = OpenAIProvider(Settings(), sdk)
    try:
        with pytest.raises(AppError) as error:
            await provider.answer(question, evidence(), [], plan=plan)
        assert error.value.code == "invalid_model_output"
    finally:
        await provider.close()
