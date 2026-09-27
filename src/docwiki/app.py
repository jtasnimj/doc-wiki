import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from docwiki.config import Settings
from docwiki.contracts import BatchResponse, ErrorResponse, ResultError, normalize_questions
from docwiki.errors import AppError
from docwiki.json_source import parse_json
from docwiki.observability import configure_logging, event, request_id
from docwiki.providers import OpenAIProvider, Provider
from docwiki.service import QAService


def error_response(error: AppError):
    return JSONResponse(
        ErrorResponse(
            error=ResultError(code=error.code, message=error.message), request_id=request_id.get()
        ).model_dump(),
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

        async def bounded_receive():
            nonlocal count
            message = await receive()
            count += len(message.get("body", b""))
            if count > self.settings.body_bytes:
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
                    ]
                )
                if not any(name == b"content-security-policy" for name, _ in message["headers"]):
                    message["headers"].append(
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self'; "
                            b"object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                        )
                    )
            await send(message)

        try:
            async with asyncio.timeout(self.settings.request_timeout):
                await self.app(scope, bounded_receive, tagged_send)
        except TimeoutError:
            event("request_error", error_category="request_timeout")
            if not response_started:
                await error_response(
                    AppError("request_timeout", "Request deadline exceeded.", 504)
                )(scope, receive, tagged_send)
        except AppError as exc:
            event("request_error", error_category=exc.code)
            if not response_started:
                await error_response(exc)(scope, receive, tagged_send)
        except Exception:
            event("request_error", error_category="internal_error")
            if not response_started:
                await error_response(
                    AppError("internal_error", "The request could not be processed.", 500)
                )(scope, receive, tagged_send)
        finally:
            event(
                "request_complete",
                status=status,
                latency_ms=round((time.monotonic() - started) * 1000),
            )
            request_id.reset(token)


def multipart_schema():
    descriptions = {
        "document_file": "PDF or JSON source document, up to 10 MiB.",
        "questions_file": (
            "JSON list of strings or records containing question and optional id, "
            "optionally under a questions wrapper. Up to 20 questions and 256 KiB."
        ),
    }
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": list(descriptions),
                        "properties": {
                            name: {"type": "string", "format": "binary", "description": description}
                            for name, description in descriptions.items()
                        },
                    }
                }
            },
        }
    }


def error_schemas():
    errors = {
        400: (
            "Malformed questions JSON or multipart encoding.",
            "invalid_json",
            "Supply valid UTF-8 questions JSON.",
        ),
        413: (
            "An uploaded file or the request exceeds its size limit.",
            "upload_too_large",
            "An uploaded file exceeds its size limit.",
        ),
        415: (
            "Unsupported file type.",
            "unsupported_format",
            "Use JSON questions and a PDF or JSON document.",
        ),
        422: (
            "Invalid file fields, question values, or source content.",
            "invalid_questions",
            "Supply 1–20 questions.",
        ),
        500: (
            "Unexpected server failure.",
            "internal_error",
            "The request could not be processed.",
        ),
        502: (
            "Document ingestion received an invalid provider response.",
            "invalid_embeddings",
            "Provider returned invalid embeddings.",
        ),
        503: (
            "Provider configuration, access, quota, or availability failure during ingestion.",
            "provider_unavailable",
            "Provider could not complete the request.",
        ),
        504: (
            "Extraction or request deadline exceeded before answering.",
            "extraction_timeout",
            "PDF extraction timed out.",
        ),
    }
    return {
        status: {
            "model": ErrorResponse,
            "description": description,
            "content": {
                "application/json": {
                    "example": {
                        "error": {"code": code, "message": message},
                        "request_id": "0123456789abcdef0123456789abcdef",
                    }
                }
            },
        }
        for status, (description, code, message) in errors.items()
    }


async def read_uploads(request: Request, settings: Settings):
    expected = {"document_file", "questions_file"}
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "multipart/form-data":
        raise AppError("invalid_upload", "Use multipart/form-data with both uploaded files.", 400)
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
        if str(exc.detail).startswith(("Too many files.", "Too many fields.")):
            raise AppError("invalid_upload", "Supply exactly the documented file fields.") from None
        raise AppError("invalid_upload", "Malformed multipart encoding.", 400) from None


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

    @app.get("/docs", include_in_schema=False)
    async def api_docs():
        nonce = uuid.uuid4().hex
        page = get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="DocWiki · API documentation",
            swagger_favicon_url="/static/favicon.svg",
            swagger_ui_parameters={"validatorUrl": None, "displayRequestDuration": True},
        )
        html = bytes(page.body).decode().replace("<script>", f'<script nonce="{nonce}">')
        return HTMLResponse(
            html,
            headers={
                "Content-Security-Policy": (
                    "default-src 'self'; "
                    f"script-src 'self' https://cdn.jsdelivr.net 'nonce-{nonce}'; "
                    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                    "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
                    "frame-ancestors 'none'"
                )
            },
        )

    @app.exception_handler(AppError)
    async def known_error(request, exc):
        event("request_error", error_category=exc.code)
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error_response(
            AppError("invalid_request", "Request does not match the documented schema.")
        )

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.post(
        "/api/qa",
        summary="Answer questions from uploaded files",
        description=(
            "Upload a questions JSON file and a PDF or JSON source. Results preserve input order "
            "and duplicate questions. Once ingestion succeeds, answering failures remain "
            "per-question errors in an HTTP 200 batch, including all-failed batches and "
            "answering deadlines."
        ),
        response_model=BatchResponse,
        responses=error_schemas(),
        openapi_extra=multipart_schema(),
    )
    async def qa(request: Request):
        files, kind = await read_uploads(request, settings)
        try:
            questions = normalize_questions(parse_json(files["questions_file"], settings), settings)
        except AppError as exc:
            if exc.code == "invalid_json":
                raise AppError(exc.code, exc.message, 400) from None
            raise

        async def operation():
            service = request.app.state.service
            info = await service.ingest(files["document_file"], kind)
            return await service.questions(
                info.document_id, questions, request.state.deadline, ready_document=info
            )

        return await connected_work(request, operation())

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(static / "index.html")

    return app


app = create_app()
