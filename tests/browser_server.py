"""Explicit offline browser-test server. Never use it to evaluate answer quality."""

import asyncio
import tempfile
from pathlib import Path

import uvicorn

from docwiki.app import create_app
from docwiki.config import Settings
from docwiki.contracts import ModelAnswer
from docwiki.errors import AppError
from docwiki.offline import FakeProvider


class BrowserProvider(FakeProvider):
    async def answer(self, question, evidence, warnings):
        await asyncio.sleep(0.15)
        if question == "Missing fact?":
            return ModelAnswer(
                status="not_found", answer="The document does not specify a region.", source_ids=[]
            )
        if question == "Related fact?":
            return ModelAnswer.model_validate(
                {
                    "status": "not_found",
                    "answer": "The document does not specify a region.",
                    "source_ids": [],
                    "related_information": [
                        {
                            "text": "<img src=x onerror=window.docwikiPwned=true> "
                            "ExampleCloud hosts the service.",
                            "source_ids": [evidence[0].source_id],
                        }
                    ],
                }
            )
        if question == "Partial fact?":
            return ModelAnswer(
                status="partial",
                answer="ExampleCloud is documented; the requested region is missing.",
                source_ids=[evidence[0].source_id],
            )
        if question == "Fail this question?":
            raise AppError("provider_unavailable", "Provider could not complete the request.", 503)
        return await super().answer(question, evidence, warnings)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="docwiki-browser-") as folder:
        app = create_app(
            Settings(data_dir=Path(folder) / "data", embedding_dimensions=64), BrowserProvider()
        )
        uvicorn.run(app, host="127.0.0.1", port=8765)
