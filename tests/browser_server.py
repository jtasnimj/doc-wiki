"""Explicit offline browser-test server. Never use it to evaluate answer quality."""

import asyncio
import tempfile
from pathlib import Path

import uvicorn

from docwiki.app import create_app
from docwiki.config import Settings
from docwiki.offline import FakeProvider


class BrowserProvider(FakeProvider):
    async def answer(self, question, evidence, warnings):
        # A short deterministic delay makes the loading state observable in the browser.
        await asyncio.sleep(0.15)
        return await super().answer(question, evidence, warnings)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="docwiki-browser-") as folder:
        app = create_app(
            Settings(data_dir=Path(folder) / "data", embedding_dimensions=64), BrowserProvider()
        )
        uvicorn.run(app, host="127.0.0.1", port=8765)
