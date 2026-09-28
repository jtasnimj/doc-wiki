import asyncio
import json
import sys
import tempfile
from pathlib import Path

from doc_wiki.config import Settings
from doc_wiki.contracts import Extraction
from doc_wiki.errors import AppError


class PDFExtractor:
    def __init__(self, settings: Settings, worker_command: list[str] | None = None):
        self.settings = settings
        self.slots = asyncio.Semaphore(settings.pdf_concurrency)
        self.command = worker_command or [sys.executable, "-m", "doc_wiki.pdf_worker"]

    async def run(self, path: Path, options: dict) -> dict:
        process = None
        try:
            async with asyncio.timeout(self.settings.extraction_timeout), self.slots:
                with tempfile.TemporaryDirectory(prefix="docwiki-pdf-") as folder:
                    output = Path(folder) / "result.json"
                    try:
                        process = await asyncio.create_subprocess_exec(
                            *self.command,
                            str(path),
                            str(output),
                            json.dumps(options),
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await process.wait()

                        def read_result():
                            if process.returncode != 0 or not output.exists():
                                raise AppError("parser_failed", "PDF extraction failed.", 422)
                            if output.stat().st_size > self.settings.extracted_bytes * 5:
                                raise AppError(
                                    "extracted_limit", "PDF extraction exceeded the size limit."
                                )
                            return json.loads(output.read_text())

                        value = await asyncio.to_thread(read_result)
                    finally:
                        if process is not None and process.returncode is None:

                            async def stop():
                                try:
                                    process.terminate()
                                except ProcessLookupError:
                                    pass
                                try:
                                    await asyncio.wait_for(process.wait(), timeout=1)
                                except TimeoutError:
                                    process.kill()
                                    await process.wait()

                            task = asyncio.create_task(stop())
                            try:
                                await asyncio.shield(task)
                            except asyncio.CancelledError:
                                await task
                                raise
                    if "error" in value:
                        messages = {
                            "encrypted_pdf": "Encrypted PDFs are unsupported.",
                            "pdf_page_limit": "PDF page count exceeds the configured limit.",
                            "no_usable_text": "No usable text found. OCR is disabled.",
                            "extracted_limit": "PDF text exceeds the configured limit.",
                        }
                        raise AppError(
                            value["error"],
                            messages.get(value["error"], "The PDF is corrupt or unsupported."),
                        )
                    return value
        except TimeoutError as exc:
            raise AppError("extraction_timeout", "PDF extraction timed out.", 504) from exc

    async def extract(self, path: Path) -> Extraction:
        return Extraction.model_validate(
            await self.run(
                path,
                {
                    "pdf_pages": self.settings.pdf_pages,
                    "extracted_bytes": self.settings.extracted_bytes,
                },
            )
        )
