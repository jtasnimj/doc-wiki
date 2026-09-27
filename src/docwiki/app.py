import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from docwiki.config import Settings
from docwiki.contracts import BatchResponse, DocumentInfo, normalize_questions
from docwiki.errors import AppError
from docwiki.json_source import parse_json
from docwiki.observability import configure_logging, event, request_id
from docwiki.providers import OpenAIProvider, Provider
from docwiki.service import QAService


def error_response(error: AppError):
    return JSONResponse(
        {"error": {"code": error.code, "message": error.message}, "request_id": request_id.get()},
        status_code=error.status,
    )


class RequestBounds:
    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = request_id.set(uuid.uuid4().hex)
        started = time.monotonic()
        scope.setdefault("state", {})["deadline"] = started + self.settings.request_timeout
        count, response_started, status = 0, False, 500
        limit = (
            self.settings.questions_bytes
            if scope["path"].endswith("/questions")
            else self.settings.body_bytes
        )

        async def bounded_receive():
            nonlocal count
            message = await receive()
            count += len(message.get("body", b""))
            if count > limit:
                raise AppError("upload_too_large", "Request exceeds the upload limit.", 413)
            return message

        async def tagged_send(message):
            nonlocal response_started, status
            if message["type"] == "http.response.start":
                response_started, status = True, message["status"]
                message["headers"].extend(
                    [
                        (b"x-request-id", request_id.get().encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self'; "
                            b"object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                        ),
                    ]
                )
            await send(message)

        try:
            async with asyncio.timeout(self.settings.request_timeout):
                await self.app(scope, bounded_receive, tagged_send)
        except TimeoutError:
            if not response_started:
                await error_response(
                    AppError("request_timeout", "Request deadline exceeded.", 504)
                )(scope, receive, tagged_send)
        except AppError as exc:
            if not response_started:
                await error_response(exc)(scope, receive, tagged_send)
        finally:
            event(
                "request_complete",
                status=status,
                latency_ms=round((time.monotonic() - started) * 1000),
            )
            request_id.reset(token)


def multipart_schema(questions: bool = False):
    names = ["document_file"] + (["questions_file"] if questions else [])
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": names,
                        "properties": {
                            name: {"type": "string", "format": "binary"} for name in names
                        },
                    }
                }
            },
        }
    }


def question_schema():
    item = {
        "oneOf": [
            {"type": "string"},
            {
                "type": "object",
                "required": ["question"],
                "properties": {"question": {"type": "string"}, "id": {"type": "string"}},
            },
        ]
    }
    schema = {
        "type": "object",
        "required": ["questions"],
        "properties": {"questions": {"type": "array", "items": item}},
    }
    return {"requestBody": {"required": True, "content": {"application/json": {"schema": schema}}}}


async def read_uploads(request: Request, settings: Settings, batch: bool):
    expected = {"document_file", "questions_file"} if batch else {"document_file"}
    try:
        async with request.form(
            max_files=len(expected), max_fields=0, max_part_size=settings.document_bytes
        ) as form:
            if set(form) != expected or len(form.multi_items()) != len(expected):
                raise AppError("invalid_upload", "Supply exactly the documented file fields.")
            data = {}
            source_type: Literal["pdf", "json"] = "json"
            for name in expected:
                item = form[name]
                if not isinstance(item, UploadFile):
                    raise AppError("invalid_upload", "Each input must be an uploaded file.")
                limit = (
                    settings.questions_bytes
                    if name == "questions_file"
                    else settings.document_bytes
                )
                if item.size is not None and item.size > limit:
                    raise AppError(
                        "upload_too_large", "An uploaded file exceeds its size limit.", 413
                    )
                raw = await item.read(limit + 1)
                if len(raw) > limit:
                    raise AppError(
                        "upload_too_large", "An uploaded file exceeds its size limit.", 413
                    )
                if not raw:
                    raise AppError("empty_upload", "Uploaded files cannot be empty.")
                suffix = Path(item.filename or "").suffix.lower()
                allowed = {".json"} if name == "questions_file" else {".json", ".pdf"}
                if suffix not in allowed:
                    raise AppError(
                        "unsupported_format", "Use JSON questions and a PDF or JSON document.", 415
                    )
                mime = item.content_type or "application/octet-stream"
                valid_mimes = {
                    "application/octet-stream",
                    "application/json" if suffix == ".json" else "application/pdf",
                }
                if mime not in valid_mimes:
                    raise AppError(
                        "unsupported_format",
                        "The declared file type does not match its format.",
                        415,
                    )
                if suffix == ".pdf" and not raw.lstrip().startswith(b"%PDF-"):
                    raise AppError("invalid_pdf", "The uploaded file is not a PDF.")
                data[name] = raw
                if name == "document_file":
                    source_type = "pdf" if suffix == ".pdf" else "json"
            return data, source_type
    except HTTPException as exc:
        raise AppError("invalid_upload", "Malformed multipart upload or too many fields.") from exc


async def connected_work(request: Request, operation):
    """The upload is consumed before watching for disconnects; no competing readers."""

    async def disconnected():
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                return

    work = asyncio.create_task(operation)
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait([work, watcher], return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return work.result()
        raise AppError("client_disconnected", "Client disconnected.", 499)
    finally:
        for task in (work, watcher):
            if not task.done():
                task.cancel()
        await asyncio.gather(work, watcher, return_exceptions=True)


def create_app(settings: Settings | None = None, provider: Provider | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        service = QAService(settings, provider or OpenAIProvider(settings))
        await service.start()
        app.state.service = service
        try:
            yield
        finally:
            await service.close()

    app = FastAPI(
        title="DocWiki", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.add_middleware(RequestBounds, settings=settings)

    @app.exception_handler(AppError)
    async def known_error(request, exc):
        event("request_error", error_category=exc.code)
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error_response(
            AppError("invalid_request", "Request does not match the documented schema.")
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        event("request_error", error_category="internal_error")
        return error_response(
            AppError("internal_error", "The request could not be processed.", 500)
        )

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.post("/api/qa", response_model=BatchResponse, openapi_extra=multipart_schema(True))
    async def qa(request: Request):
        files, kind = await read_uploads(request, settings, True)
        questions = normalize_questions(parse_json(files["questions_file"], settings), settings)

        async def operation():
            service = request.app.state.service
            info = await service.ingest(files["document_file"], kind)
            return await service.questions(info.document_id, questions, request.state.deadline)

        return await connected_work(request, operation())

    @app.post("/api/documents", response_model=DocumentInfo, openapi_extra=multipart_schema())
    async def documents(request: Request):
        files, kind = await read_uploads(request, settings, False)
        return await connected_work(
            request, request.app.state.service.ingest(files["document_file"], kind)
        )

    @app.post(
        "/api/documents/{document_id}/questions",
        response_model=BatchResponse,
        openapi_extra=question_schema(),
    )
    async def questions(document_id: str, request: Request):
        value = parse_json(await request.body(), settings)
        if not isinstance(value, dict) or "questions" not in value:
            raise AppError("invalid_questions", "Use an object containing questions.")
        normalized = normalize_questions(value, settings)
        return await connected_work(
            request,
            request.app.state.service.questions(document_id, normalized, request.state.deadline),
        )

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(static / "index.html")

    return app


app = create_app()
