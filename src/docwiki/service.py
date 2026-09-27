import asyncio
import shutil
import time
from pathlib import Path
from typing import Literal
from weakref import WeakValueDictionary

from filelock import FileLock, Timeout

from docwiki.config import Settings
from docwiki.contracts import (
    BatchResponse,
    Citation,
    DocumentInfo,
    Evidence,
    Extraction,
    ModelAnswer,
    Question,
    RelatedInformation,
    Result,
    ResultError,
)
from docwiki.errors import AppError
from docwiki.json_source import extract_json
from docwiki.observability import event
from docwiki.pdf import PDFExtractor
from docwiki.providers import Provider
from docwiki.retrieval import PARSER_VERSION, IndexStore, make_nodes


def storage_lock(root: Path) -> FileLock:
    root = root.resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(root.parent / f".{root.name}.lock")


def validate_answer(question: Question, answer: ModelAnswer, evidence: list[Evidence]) -> Result:
    allowed = {item.source_id: item for item in evidence}
    ids = list(dict.fromkeys(answer.source_ids))
    related_ids = [ident for item in answer.related_information for ident in item.source_ids]
    invalid = (
        not answer.answer.strip()
        or any(ident not in allowed for ident in [*ids, *related_ids])
        or (answer.status == "not_found" and bool(ids))
        or (answer.status != "not_found" and not ids)
        or (answer.status != "not_found" and bool(answer.related_information))
        or any(not item.text.strip() for item in answer.related_information)
    )
    if invalid:
        raise AppError("invalid_model_output", "Answer or citations failed validation.", 502)

    def citations(source_ids: list[str]) -> list[Citation]:
        return [
            Citation(
                source_id=ident,
                kind=allowed[ident].kind,
                locations=[allowed[ident].location],
                excerpt=allowed[ident].text,
                derived=allowed[ident].kind == "vision",
            )
            for ident in dict.fromkeys(source_ids)
        ]

    return Result(
        **question.model_dump(),
        answer=answer.answer,
        status=answer.status,
        citations=citations(ids),
        related_information=[
            RelatedInformation(text=item.text, citations=citations(item.source_ids))
            for item in answer.related_information
        ],
    )


def failed(question: Question, error: AppError) -> Result:
    return Result(
        **question.model_dump(),
        answer=None,
        status="error",
        error=ResultError(code=error.code, message=error.message),
    )


class QAService:
    def __init__(self, settings: Settings, provider: Provider, pdf: PDFExtractor | None = None):
        self.settings, self.provider = settings, provider
        self.pdf = pdf or PDFExtractor(settings)
        self.store = IndexStore(settings, provider)
        self.locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self.lock = storage_lock(settings.data_dir)

    async def start(self):
        try:
            self.lock.acquire(timeout=0)
        except Timeout:
            raise RuntimeError(
                "This data directory is already in use. Run one API process."
            ) from None
        try:
            await self.store.start()
        except BaseException:
            self.lock.release()
            raise

    async def close(self):
        try:
            await self.store.close()
            await self.provider.close()
        finally:
            self.lock.release()

    async def ingest(self, raw: bytes, source_type: Literal["pdf", "json"]) -> DocumentInfo:
        doc_id = self.store.document_id(raw)
        lock = self.locks.setdefault(doc_id, asyncio.Lock())
        async with lock:
            cached = await self.store.run(self.store.ready, doc_id)
            if cached:
                event(
                    "ingestion",
                    document_id=doc_id,
                    index_cache_hit=True,
                    chunk_count=cached.chunk_count,
                )
                return cached
            started = time.monotonic()
            directory = self.store.directory(doc_id)
            try:
                await self.store.run(directory.mkdir, 0o700, True, True)
                path = directory / f"source.{source_type}"
                await self.store.run(path.write_bytes, raw)
                extraction = (
                    await self.pdf.extract(path)
                    if source_type == "pdf"
                    else await self.store.run(extract_json, raw, self.settings)
                )
                # Optional vision is attached here only when explicitly enabled.
                if self.settings.vision_enabled and source_type == "pdf":
                    extraction = await self.enrich(extraction, path, directory)
                nodes = await self.store.run(make_nodes, extraction, doc_id, self.settings)
                vectors = await self.store.embedder.aget_text_embedding_batch(
                    [n.text for n in nodes]
                )
                for node, vector in zip(nodes, vectors, strict=True):
                    node.embedding = vector
                await self.store.run(self.store.index, doc_id, nodes)
                info = DocumentInfo(
                    document_id=doc_id,
                    source_type=source_type,
                    page_count=extraction.page_count,
                    chunk_count=len(nodes),
                    warnings=extraction.warnings,
                )
                await self.store.run(
                    (directory / "extraction.json").write_text, extraction.model_dump_json()
                )
                await self.store.run(self.store.mark_ready, info)
                event(
                    "ingestion",
                    document_id=doc_id,
                    parser="pymupdf" if source_type == "pdf" else "json",
                    extraction_method=PARSER_VERSION if source_type == "pdf" else "json-record",
                    page_count=info.page_count,
                    chunk_count=info.chunk_count,
                    skipped_pages=len(extraction.skipped_pages),
                    index_cache_hit=False,
                    latency_ms=round((time.monotonic() - started) * 1000),
                )
                return info
            except BaseException:
                # Clean only this failed request; no background recovery subsystem.
                await self.store.run(self.store.remove_index, doc_id)
                await self.store.run(shutil.rmtree, directory, True)
                raise

    async def enrich(self, extraction: Extraction, path: Path, directory: Path) -> Extraction:
        # Implemented after the development figure gate; baseline never calls it.
        from docwiki.contracts import Location, SourceBlock

        selected = extraction.visual_candidates[: self.settings.vision_crops]
        if not selected:
            return extraction
        output = await self.pdf.run(
            path,
            {
                "render": True,
                "output_dir": str(directory),
                "locations": [loc.model_dump() for loc in selected],
            },
        )
        for image in output["images"]:
            description = await self.provider.describe(Path(image["path"]))
            extraction.blocks.append(
                SourceBlock(
                    text=description,
                    kind="vision",
                    method="gpt-4o-mini-vision",
                    location=Location.model_validate(image["location"]),
                    image_ref=image["path"],
                )
            )
        extraction.warnings.append(
            f"Added derived descriptions for {len(selected)} crops; coverage remains heuristic."
        )
        if len(extraction.visual_candidates) > len(selected):
            extraction.warnings.append(
                "Visual budget reached; some potential figures were not processed."
            )
        return extraction

    async def questions(
        self,
        doc_id: str,
        questions: list[Question],
        deadline: float,
        *,
        ready_document: DocumentInfo | None = None,
    ) -> BatchResponse:
        # The canonical route already established readiness. Avoid re-entering the
        # storage queue after ingestion consumed most of this request's deadline.
        info = ready_document or await self.store.run(self.store.ready, doc_id)
        if info is None:
            raise AppError(
                "document_not_found", "No ready index exists for this document/configuration.", 404
            )
        unique: dict[str, Question] = {}
        for question in questions:
            unique.setdefault(question.question, question)

        async def one(question: Question):
            try:
                if time.monotonic() >= deadline - 0.05:
                    return failed(
                        question,
                        AppError("request_timeout", "Question exceeded the request deadline.", 504),
                    )
                embedding = await self.store.embedder.aget_query_embedding(question.question)
                evidence = await self.store.run(
                    self.store.retrieve,
                    doc_id,
                    question.question,
                    embedding,
                    finish_on_cancel=False,
                )
                if not evidence:
                    return Result(
                        **question.model_dump(),
                        status="not_found",
                        answer="Not found in the provided document.",
                    )
                answer = await self.provider.answer(question.question, evidence, info.warnings)
                return validate_answer(question, answer, evidence)
            except AppError as exc:
                return failed(question, exc)
            except Exception:
                event("question_error", document_id=doc_id, error_category="processing_error")
                return failed(
                    question,
                    AppError("processing_error", "The question could not be processed.", 500),
                )

        tasks = {text: asyncio.create_task(one(q)) for text, q in unique.items()}
        try:
            _, pending = await asyncio.wait(
                tasks.values(), timeout=max(0, deadline - time.monotonic() - 0.05)
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            results = []
            for question in questions:
                task = tasks[question.question]
                result = (
                    failed(
                        question,
                        AppError("request_timeout", "Question exceeded the request deadline.", 504),
                    )
                    if task.cancelled()
                    else task.result().model_copy(update=question.model_dump())
                )
                results.append(result)
        finally:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
        errors = sum(result.status == "error" for result in results)
        event("batch_complete", document_id=doc_id, question_count=len(results), errors=errors)
        return BatchResponse(
            document_id=doc_id,
            results=results,
            warnings=info.warnings,
            batch_status="completed"
            if not errors
            else "failed"
            if errors == len(results)
            else "partial_failure",
        )
