from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from docwiki.config import Settings
from docwiki.errors import AppError


class Question(BaseModel):
    id: str
    question: str


def normalize_questions(value: Any, settings: Settings) -> list[Question]:
    if isinstance(value, dict):
        value = value.get("questions")
    if not isinstance(value, list) or not 1 <= len(value) <= settings.questions_limit:
        raise AppError("invalid_questions", f"Supply 1–{settings.questions_limit} questions.")
    explicit: set[str] = set()
    parsed: list[tuple[str | None, str]] = []
    ident: str | None
    for item in value:
        ident, wording = (None, item) if isinstance(item, str) else (None, None)
        if isinstance(item, dict):
            ident, wording = item.get("id"), item.get("question")
            if "id" in item and (
                not isinstance(ident, str) or not ident.strip() or len(ident) > 128
            ):
                raise AppError(
                    "invalid_question_id",
                    "Question IDs must be non-empty strings up to 128 characters.",
                )
        if (
            not isinstance(wording, str)
            or not wording.strip()
            or len(wording) > settings.question_chars
        ):
            raise AppError(
                "invalid_question",
                f"Questions must contain 1–{settings.question_chars} characters.",
            )
        if ident is not None:
            if ident in explicit:
                raise AppError("duplicate_question_id", "Explicit question IDs must be unique.")
            explicit.add(ident)
        parsed.append((ident, wording))
    result = []
    used = set(explicit)
    for position, (ident, wording) in enumerate(parsed, 1):
        if ident is None:
            ident = f"q{position}"
            while ident in used:
                ident = "_" + ident
        used.add(ident)
        result.append(Question(id=ident, question=wording))
    return result


class Location(BaseModel):
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    json_path: str | None = None


class SourceBlock(BaseModel):
    text: str
    kind: Literal["pdf", "json", "vision"]
    location: Location
    method: str
    section: str | None = None
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    image_ref: str | None = None


class Extraction(BaseModel):
    blocks: list[SourceBlock]
    page_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
    visual_candidates: list[Location] = Field(default_factory=list)
    skipped_pages: list[int] = Field(default_factory=list)


class Evidence(BaseModel):
    source_id: str
    text: str
    kind: Literal["pdf", "json", "vision"]
    location: Location
    method: str
    image_ref: str | None = None


class Citation(BaseModel):
    source_id: str
    kind: Literal["pdf", "json", "vision"]
    locations: list[Location]
    excerpt: str
    derived: bool = False


class ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    status: Literal["answered", "partial", "not_found"]
    source_ids: list[str]


class ResultError(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ResultError
    request_id: str


class Result(Question):
    answer: str | None
    status: Literal["answered", "partial", "not_found", "error"]
    citations: list[Citation] = Field(default_factory=list)
    error: ResultError | None = None


class DocumentInfo(BaseModel):
    document_id: str
    source_type: Literal["pdf", "json"]
    page_count: int | None
    chunk_count: int
    warnings: list[str]
    cache_hit: bool = False


class BatchResponse(BaseModel):
    document_id: str
    results: list[Result]
    warnings: list[str]
    batch_status: Literal["completed", "partial_failure", "failed"]
