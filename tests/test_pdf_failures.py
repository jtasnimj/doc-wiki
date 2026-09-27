import asyncio
import os
import sys
from pathlib import Path

import pytest

from docwiki.config import Settings
from docwiki.errors import AppError
from docwiki.pdf import PDFExtractor


async def test_pdf_rejection_limits_and_partial_coverage(tmp_path):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "tests/make_pdf_failures.py", str(tmp_path)
    )
    assert await process.wait() == 0
    extractor = PDFExtractor(Settings())
    short = await extractor.extract(tmp_path / "short.pdf")
    assert any("Cloud: ExampleCloud." in block.text for block in short.blocks)
    for name, code in [
        ("blank", "no_usable_text"),
        ("encrypted", "encrypted_pdf"),
        ("corrupt", "invalid_pdf"),
    ]:
        with pytest.raises(AppError) as result:
            await extractor.extract(tmp_path / f"{name}.pdf")
        assert result.value.code == code
    with pytest.raises(AppError) as result:
        await PDFExtractor(Settings(pdf_pages=1)).extract(tmp_path / "partial.pdf")
    assert result.value.code == "pdf_page_limit"
    partial = await extractor.extract(tmp_path / "partial.pdf")
    assert partial.skipped_pages == [2]
    assert any("2" in warning and "OCR is disabled" in warning for warning in partial.warnings)
    assert all(b.location.page == 1 for b in partial.blocks)


async def test_cancelled_pdf_work_is_reaped_and_cleaned(tmp_path):
    worker = PDFExtractor(Settings(), [sys.executable, "tests/slow_pdf.py"])
    path = tmp_path / "slow.pdf"
    task = asyncio.create_task(worker.extract(path))
    async with asyncio.timeout(3):
        # The isolated child signals readiness by file; it cannot share an asyncio.Event.
        while not Path(str(path) + ".output").exists():  # noqa: ASYNC110
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pid = int(Path(str(path) + ".pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not Path(Path(str(path) + ".output").read_text()).parent.exists()
    assert (await worker.extract(tmp_path / "fast.pdf")).page_count == 1
