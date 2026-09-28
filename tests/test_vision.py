import asyncio
import sys
import time

from doc_wiki.config import Settings
from doc_wiki.contracts import ModelAnswer, Question
from doc_wiki.service import QAService
from tests.fakes import FakeProvider


async def test_optional_vision_is_capped_cached_and_cites_original_locations(tmp_path):
    path = tmp_path / "figures.pdf"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "tests/make_figure.py", str(path)
    )
    assert await process.wait() == 0

    class VisualProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.visual_calls = 0
            self.answer_evidence = []

        async def describe(self, image):
            self.visual_calls += 1
            assert image.read_bytes().startswith(b"\x89PNG")
            return "Primary region west. Backup region east."

        async def answer(self, question, evidence, warnings):
            self.answer_evidence = evidence
            visual = [e for e in evidence if e.kind == "vision"]
            return ModelAnswer(
                answer="The primary region is west.",
                status="answered",
                source_ids=[visual[0].source_id],
            )

    raw = path.read_bytes()
    baseline_provider = VisualProvider()
    settings = Settings(data_dir=tmp_path / "baseline", embedding_dimensions=64)
    baseline = QAService(settings, baseline_provider)
    await baseline.start()
    try:
        info = await baseline.ingest(raw, "pdf")
        assert baseline_provider.visual_calls == 0
        assert any("figure" in warning for warning in info.warnings)
    finally:
        await baseline.close()
    provider = VisualProvider()
    service = QAService(
        settings.model_copy(update={"data_dir": tmp_path / "vision", "vision_enabled": True}),
        provider,
    )
    await service.start()
    try:
        info = await service.ingest(raw, "pdf")
        assert provider.visual_calls == 3
        assert any("budget" in warning.lower() for warning in info.warnings)
        assert (await service.ingest(raw, "pdf")).cache_hit
        assert provider.visual_calls == 3
        result = await service.questions(
            info.document_id,
            [Question(id="q", question="Primary region west backup east?")],
            time.monotonic() + 5,
        )
        assert result.results[0].status == "answered"
        assert result.results[0].citations[0].derived
        assert result.results[0].citations[0].locations[0].page in [1, 2, 3]
        assert sum(bool(e.image_ref) for e in provider.answer_evidence) <= 2
        assert all(e.image_ref for e in provider.answer_evidence if e.kind == "vision")
    finally:
        await service.close()
