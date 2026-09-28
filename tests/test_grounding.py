import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from doc_wiki.app import create_app
from doc_wiki.config import Settings
from doc_wiki.contracts import Evidence, Location, ModelAnswer, Question
from doc_wiki.errors import AppError
from doc_wiki.service import validate_answer
from tests.fakes import FakeProvider


@pytest.fixture
async def qa(tmp_path):
    provider = FakeProvider()
    app = create_app(Settings(data_dir=tmp_path, embedding_dimensions=64), provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, provider


def uploads(questions, source=None):
    return {
        "document_file": (
            "source.json",
            json.dumps(source or {"hosting": "ExampleCloud"}).encode(),
            "application/json",
        ),
        "questions_file": ("questions.json", json.dumps(questions).encode(), "application/json"),
    }


async def test_not_found_preserves_the_specific_missing_information(qa):
    client, provider = qa
    explanation = "The available evidence does not specify a hosting region."
    provider.answers["Which region?"] = ModelAnswer(
        status="not_found", answer=explanation, source_ids=[]
    )
    response = await client.post("/api/qa", files=uploads(["Which region?"]))
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "not_found"
    assert result["answer"] == explanation
    assert result["citations"] == []
    assert "related_information" not in result


async def test_related_facts_have_separate_server_derived_citations_and_preserve_duplicates(qa):
    client, provider = qa

    async def answer(question, evidence, warnings):
        provider.answer_calls += 1
        return ModelAnswer.model_validate(
            {
                "status": "not_found",
                "answer": "The available evidence does not specify a hosting region.",
                "source_ids": [],
                "related_information": [
                    {"text": "Hosting uses ExampleCloud.", "source_ids": [evidence[0].source_id]}
                ],
            }
        )

    provider.answer = answer
    response = await client.post(
        "/api/qa",
        files=uploads(
            [
                {"id": "first", "question": "Which region?"},
                {"id": "copy", "question": "Which region?"},
            ]
        ),
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert [result["id"] for result in results] == ["first", "copy"]
    assert provider.answer_calls == 1
    assert results[0]["status"] == "not_found"
    assert results[0]["citations"] == []
    related = results[0]["related_information"][0]
    assert related["text"] == "Hosting uses ExampleCloud."
    assert "ExampleCloud" in related["citations"][0]["excerpt"]
    assert related["citations"][0]["locations"][0]["json_path"] == "$"
    assert results[1]["related_information"] == results[0]["related_information"]


@pytest.mark.parametrize("source_ids,text", [(["foreign-document"], "A fact."), (["s1"], "  ")])
def test_invalid_related_information_is_an_execution_error(source_ids, text):
    evidence = [
        Evidence(
            source_id="s1",
            text="Source fact.",
            kind="json",
            location=Location(json_path="$"),
            method="json-record",
        )
    ]
    answer = ModelAnswer.model_validate(
        {
            "status": "not_found",
            "answer": "The requested threshold is not specified.",
            "source_ids": [],
            "related_information": [{"text": text, "source_ids": source_ids}],
        }
    )
    with pytest.raises(AppError) as error:
        validate_answer(Question(id="q", question="Threshold?"), answer, evidence)
    assert error.value.code == "invalid_model_output"


@pytest.mark.parametrize("change", ["uncited", "too_many", "too_long", "invented_excerpt"])
def test_related_information_is_bounded_and_has_no_model_supplied_excerpts(change):
    item = {"text": "A supported fact.", "source_ids": ["s1"]}
    related = [item]
    if change == "uncited":
        item["source_ids"] = []
    elif change == "too_many":
        related = [item] * 3
    elif change == "too_long":
        item["text"] = "x" * 401
    else:
        item["excerpt"] = "Invented quotation"
    with pytest.raises(ValidationError):
        ModelAnswer.model_validate(
            {
                "status": "not_found",
                "answer": "Missing.",
                "source_ids": [],
                "related_information": related,
            }
        )


@pytest.mark.parametrize("status", ["answered", "partial"])
def test_related_information_cannot_be_promoted_to_an_answer(status):
    evidence = [
        Evidence(
            source_id="s1",
            text="Source fact.",
            kind="pdf",
            location=Location(page=2, bbox=(1, 2, 3, 4)),
            method="pymupdf-text",
        )
    ]
    answer = ModelAnswer.model_validate(
        {
            "status": status,
            "answer": "A conclusion.",
            "source_ids": ["s1"],
            "related_information": [{"text": "A fact.", "source_ids": ["s1"]}],
        }
    )
    with pytest.raises(AppError, match="validation"):
        validate_answer(Question(id="q", question="Question?"), answer, evidence)


def test_related_visual_evidence_preserves_derived_provenance():
    evidence = [
        Evidence(
            source_id="visual",
            text="Derived diagram description.",
            kind="vision",
            location=Location(page=3, bbox=(1, 2, 30, 40)),
            method="gpt-4o-mini-vision",
        )
    ]
    answer = ModelAnswer.model_validate(
        {
            "status": "not_found",
            "answer": "The diagram does not establish the requested location.",
            "source_ids": [],
            "related_information": [
                {"text": "The diagram shows a provider.", "source_ids": ["visual", "visual"]}
            ],
        }
    )
    result = validate_answer(Question(id="q", question="Region?"), answer, evidence)
    citations = result.related_information[0].citations
    assert len(citations) == 1
    assert citations[0].derived
    assert citations[0].locations[0] == evidence[0].location
    assert citations[0].excerpt == evidence[0].text


async def test_reference_answer_changes_do_not_change_provider_inputs(qa):
    client, provider = qa
    calls = []

    async def answer(question, evidence, warnings):
        calls.append((question, [item.model_dump() for item in evidence], warnings))
        return ModelAnswer(
            status="not_found", answer="The region is not documented.", source_ids=[]
        )

    provider.answer = answer
    for reference in ["PRIVATE_REFERENCE_A", "PRIVATE_REFERENCE_B"]:
        response = await client.post(
            "/api/qa",
            files=uploads(
                [
                    {
                        "id": "q",
                        "question": "Region?",
                        "answer": reference,
                        "comments": reference,
                        "confidence": reference,
                    }
                ]
            ),
        )
        assert response.status_code == 200
        assert "PRIVATE_REFERENCE" not in response.text
    assert calls[0] == calls[1]
    assert "PRIVATE_REFERENCE" not in json.dumps(calls)


async def test_forged_related_citation_remains_a_per_question_error(qa):
    client, provider = qa
    provider.answers["Region?"] = ModelAnswer.model_validate(
        {
            "status": "not_found",
            "answer": "Missing region.",
            "source_ids": [],
            "related_information": [{"text": "A foreign fact.", "source_ids": ["foreign"]}],
        }
    )
    response = await client.post("/api/qa", files=uploads(["Region?", "Cloud?"]))
    data = response.json()
    assert response.status_code == 200
    assert data["batch_status"] == "partial_failure"
    assert data["results"][0]["error"]["code"] == "invalid_model_output"
    assert data["results"][0]["answer"] is None
    assert "related_information" not in data["results"][0]
    assert data["results"][1]["status"] == "answered"


SCENARIOS = json.loads(Path("evaluation/grounding_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", SCENARIOS, ids=lambda case: case["id"])
async def test_authored_outputs_preserve_status_scope_and_related_separation(qa, case):
    client, provider = qa

    async def answer(question, evidence, warnings):
        assert question == case["question"]
        assert case["source"]["policy"] in evidence[0].text
        return ModelAnswer.model_validate(
            {
                "status": case["expected_status"],
                "answer": case["expected_answer"],
                "source_ids": []
                if case["expected_status"] == "not_found"
                else [evidence[0].source_id],
                "related_information": [
                    {"text": case["related_text"], "source_ids": [evidence[0].source_id]}
                ]
                if case["related_text"]
                else [],
            }
        )

    provider.answer = answer
    response = await client.post(
        "/api/qa", files=uploads([case["question"]], source=case["source"])
    )
    result = response.json()["results"][0]
    assert result["status"] == case["expected_status"]
    assert result["answer"] == case["expected_answer"]
    assert bool(result.get("related_information")) == bool(case["related_text"])
    citations = result["citations"] + [
        citation for item in result.get("related_information", []) for citation in item["citations"]
    ]
    for citation in citations:
        assert case["source"]["policy"] in citation["excerpt"]
        assert citation["locations"][0]["json_path"] == "$"
