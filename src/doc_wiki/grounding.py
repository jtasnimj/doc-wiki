from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from doc_wiki.contracts import Evidence, ModelAnswer, ModelRelatedInformation
from doc_wiki.errors import AppError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionPart(StrictModel):
    id: str
    spans: list[str] = Field(min_length=1)


class QuestionPlan(StrictModel):
    original: str
    parts: list[QuestionPart] = Field(min_length=1, max_length=4)
    shared_scope: list[str] = Field(default_factory=list)


def whole_question(question: str) -> QuestionPlan:
    return QuestionPlan(original=question, parts=[QuestionPart(id="q1", spans=[question])])


class PlannedPart(StrictModel):
    segment_ids: list[int] = Field(min_length=1, max_length=12)


class PlanEnvelope(StrictModel):
    segments: list[str] = Field(min_length=1, max_length=12)
    parts: list[PlannedPart] = Field(min_length=1, max_length=4)
    shared_segment_ids: list[int] = Field(max_length=12)


def compile_question_plan(question: str, draft: PlanEnvelope) -> QuestionPlan:
    def invalid():
        raise AppError("invalid_model_output", "Question plan failed validation.", 502)

    if "".join(draft.segments) != question or any(not s for s in draft.segments):
        invalid()
    valid = set(range(1, len(draft.segments) + 1))
    shared = set(draft.shared_segment_ids)
    if not shared <= valid or len(shared) != len(draft.shared_segment_ids):
        invalid()
    used = set(shared)
    parts = []
    for i, part in enumerate(draft.parts, 1):
        refs = set(part.segment_ids)
        if (
            not refs <= valid
            or len(refs) != len(part.segment_ids)
            or not refs - shared
            or (refs - shared) & used
        ):
            invalid()
        used.update(refs)
        parts.append(QuestionPart(id=f"q{i}", spans=[draft.segments[n - 1] for n in sorted(refs)]))
    if used != valid:
        invalid()
    return QuestionPlan(
        original=question,
        parts=parts,
        shared_scope=[draft.segments[n - 1] for n in sorted(shared)],
    )


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=700)
    source_ids: list[str] = Field(min_length=1, max_length=6)
    question_part_ids: list[str] = Field(min_length=1, max_length=4)


class Gap(StrictModel):
    text: str = Field(min_length=1, max_length=300)
    question_part_ids: list[str] = Field(min_length=1, max_length=4)


class AnsweredOutcome(StrictModel):
    outcome: Literal["answered"]
    claims: list[Claim] = Field(min_length=1, max_length=8)


class MissingOutcome(StrictModel):
    outcome: Literal["not_found"]
    missing: list[Gap] = Field(min_length=1, max_length=8)
    related_information: list[ModelRelatedInformation] = Field(max_length=2)


class PartialOutcome(StrictModel):
    outcome: Literal["partial"]
    claims: list[Claim] = Field(min_length=1, max_length=8)
    missing: list[Gap] = Field(min_length=1, max_length=8)


class ConflictingOutcome(StrictModel):
    outcome: Literal["conflicting"]
    alternatives: list[Claim] = Field(min_length=2, max_length=4)


class AnswerEnvelope(StrictModel):
    result: AnsweredOutcome | PartialOutcome | ConflictingOutcome | MissingOutcome


def compile_answer(
    envelope: AnswerEnvelope, plan: QuestionPlan, evidence: list[Evidence]
) -> ModelAnswer:
    allowed = {item.source_id for item in evidence}
    parts = {part.id for part in plan.parts}
    covered: set[str] = set()

    def invalid():
        raise AppError("invalid_model_output", "Answer or coverage failed validation.", 502)

    def citations(ids):
        if any(ident not in allowed for ident in ids):
            invalid()

    def part_ids(item):
        if not item.text.strip() or any(ident not in parts for ident in item.question_part_ids):
            invalid()
        covered.update(item.question_part_ids)

    result = envelope.result
    statements, source_ids = [], []
    related = []
    status: Literal["answered", "partial", "not_found"]
    if isinstance(result, ConflictingOutcome):
        status = "partial"
        if len({claim.text.strip() for claim in result.alternatives}) < 2:
            invalid()
        for claim in result.alternatives:
            part_ids(claim)
            citations(claim.source_ids)
            source_ids.extend(claim.source_ids)
        statements.append(
            "The evidence contains conflicting statements: "
            + "; ".join(claim.text.strip().rstrip(".") for claim in result.alternatives)
            + "."
        )
    else:
        status = result.outcome
    if isinstance(result, (AnsweredOutcome, PartialOutcome)):
        for claim in result.claims:
            part_ids(claim)
            citations(claim.source_ids)
            statements.append(claim.text.strip())
            source_ids.extend(claim.source_ids)
    supported_parts = set(covered)
    if isinstance(result, (PartialOutcome, MissingOutcome)):
        for gap in result.missing:
            if len(parts) > 1 and supported_parts.intersection(gap.question_part_ids):
                invalid()
            part_ids(gap)
            statements.append(
                "The available evidence does not establish " + gap.text.strip().rstrip(".?") + "."
            )
    if isinstance(result, MissingOutcome):
        related = result.related_information
        for fact in related:
            if not fact.text.strip():
                invalid()
            citations(fact.source_ids)
    if covered != parts:
        invalid()
    return ModelAnswer(
        answer=" ".join(statements),
        status=status,
        source_ids=list(dict.fromkeys(source_ids)),
        related_information=related,
    )
