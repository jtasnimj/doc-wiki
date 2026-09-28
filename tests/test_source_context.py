import asyncio
import sys

import pytest

from docwiki.config import Settings
from docwiki.pdf import PDFExtractor


@pytest.mark.parametrize("column_order", ["original", "reverse"])
async def test_pdf_preserves_verified_heading_scope_and_table_header_provenance(
    tmp_path, column_order
):
    path = tmp_path / "context.pdf"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "tests/make_context_pdf.py", str(path), column_order
    )
    assert await process.wait() == 0
    extraction = await PDFExtractor(Settings()).extract(path)
    blocks = extraction.blocks
    assert all(b.block_id for b in blocks)
    assert len({b.block_id for b in blocks}) == len(blocks)
    meter = next(b for b in blocks if "portable meters" in b.text)
    owner = next(b for b in blocks if "Owners review" in b.text)
    assert meter.group_id == owner.group_id
    assert [(c.text, c.location.page) for c in meter.context] == [("Equipment records", 1)]
    assert meter.context[0].block_id == meter.parent_id
    table = next(b for b in blocks if b.rows)
    expected = ["Finding", "Requirement"]
    assert table.header == (expected if column_order == "original" else expected[::-1])
    assert dict(zip(table.header, table.rows[0], strict=True)) == {
        "Finding": "Not examined",
        "Requirement": "Maintain cooling",
    }
    assert table.header_location.page == 1
    assert table.header_location.bbox != table.location.bbox
    assert [c.text for c in table.context] == [
        "Supplier responsibilities",
        "Table 1: Supplier expectations excluded from examination.",
    ]
    caption = table.context[-1]
    assert caption.role == "caption" and caption.location.page == 1
    assert caption.location.bbox[3] < table.header_location.bbox[1]
    last = blocks[-1]
    assert last.location.page == 2 and last.context == []
    first_page = [b for b in blocks if b.location.page == 1]
    assert [b.location.bbox[1] for b in first_page] == sorted(
        b.location.bbox[1] for b in first_page
    )
    assert not next(b for b in blocks if b.text == "READY").section


def test_json_parent_context_keeps_complete_values_and_exact_record_paths():
    import json

    from docwiki.json_source import extract_json

    source = {
        "description": "x" * 3000,
        "tenant": "North",
        "enabled": False,
        "settings": {"refresh": 0, "backup": None},
    }
    result = extract_json(json.dumps(source).encode(), Settings())
    child = next(b for b in result.blocks if b.location.json_path == '$["settings"]')
    assert child.parent_id == "$"
    parent = child.context[0]
    assert parent.location.json_path == "$"
    assert json.loads(parent.text) == {"tenant": "North", "enabled": False}
    assert parent.omitted_values
    assert any("context" in warning.lower() for warning in result.warnings)
    description = next(b for b in result.blocks if b.location.json_path == '$["description"]')
    assert "x" * 3000 in description.text
    assert len({b.block_id for b in result.blocks}) == len(result.blocks)


async def test_indexed_passages_keep_context_and_do_not_link_unrelated_sections(tmp_path):
    from docwiki.contracts import Evidence
    from docwiki.retrieval import make_nodes

    path = tmp_path / "context.pdf"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "tests/make_context_pdf.py", str(path)
    )
    assert await process.wait() == 0
    extracted = await PDFExtractor(Settings()).extract(path)
    nodes = make_nodes(extracted, "doc_test", Settings())
    passages = [Evidence.model_validate_json(n.metadata["source"]) for n in nodes]
    meter = next(e for e in passages if "portable meters" in e.text)
    owner = next(e for e in passages if "Owners review" in e.text)
    assert meter.context[0].text == "Equipment records"
    assert meter.next_id == owner.source_id
    assert owner.previous_id == meter.source_id
    supplier = next(e for e in passages if "supplier maintains" in e.text)
    assert supplier.source_id not in [owner.next_id, meter.next_id]
    assert supplier.context[0].text == "Supplier responsibilities"
    assert meter.location.bbox != meter.context[0].location.bbox
    table = next(e for e in passages if "Not examined" in e.text)
    assert table.header_location.page == 1
    assert table.context[-1].role == "caption"
    assert "excluded from examination" in table.context[-1].text
    assert table.previous_id is None and table.next_id is None


async def test_context_citations_point_to_both_passage_and_heading(tmp_path):
    from docwiki.contracts import Evidence, ModelAnswer, Question
    from docwiki.retrieval import make_nodes
    from docwiki.service import validate_answer

    path = tmp_path / "context.pdf"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "tests/make_context_pdf.py", str(path)
    )
    assert await process.wait() == 0
    extraction = await PDFExtractor(Settings()).extract(path)
    nodes = make_nodes(extraction, "doc_test", Settings())
    evidence = [Evidence.model_validate_json(n.metadata["source"]) for n in nodes]
    supplier = next(e for e in evidence if "supplier maintains" in e.text)
    result = validate_answer(
        Question(id="q", question="Who maintains cooling?"),
        ModelAnswer(answer="The supplier.", status="answered", source_ids=[supplier.source_id]),
        evidence,
    )
    citation = result.citations[0]
    assert "Supplier responsibilities" in citation.excerpt
    assert "supplier maintains" in citation.excerpt
    assert citation.locations == [supplier.location, supplier.context[0].location]


def test_json_array_items_do_not_become_each_others_context():
    from docwiki.contracts import Evidence
    from docwiki.json_source import extract_json
    from docwiki.retrieval import make_nodes

    extraction = extract_json(
        b'["First independent record", "Second independent record"]', Settings()
    )
    nodes = make_nodes(extraction, "doc_records", Settings())
    passages = [Evidence.model_validate_json(node.metadata["source"]) for node in nodes]
    assert all(p.previous_id is None and p.next_id is None for p in passages)


@pytest.mark.parametrize("caption_style", ["ordinary", "distant", "offset"])
async def test_uncertain_nearby_text_is_not_promoted_to_table_caption(tmp_path, caption_style):
    path = tmp_path / "ambiguous.pdf"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "tests/make_context_pdf.py", str(path), "original", caption_style
    )
    assert await process.wait() == 0
    extraction = await PDFExtractor(Settings()).extract(path)
    table = next(b for b in extraction.blocks if b.rows)
    assert all(c.role != "caption" for c in table.context)
    assert any("Unrelated nearby" in b.text or "Table 1:" in b.text for b in extraction.blocks)


def test_contextual_embeddings_are_separate_from_neighbor_expansion_and_cache_compatible():
    from docwiki.contracts import Extraction, Location, SourceBlock, SourceContext
    from docwiki.retrieval import fingerprint, make_nodes
    from tests.fakes import FakeProvider

    source = Extraction(
        blocks=[
            SourceBlock(
                text="Cooling is maintained.",
                kind="pdf",
                method="pymupdf-text",
                location=Location(page=1),
                context=[
                    SourceContext(
                        block_id="heading",
                        role="heading",
                        text="Supplier responsibilities",
                        location=Location(page=1),
                    )
                ],
            )
        ]
    )
    baseline = Settings(contextual_embeddings=False)
    contextual = baseline.model_copy(update={"contextual_embeddings": True})
    original = make_nodes(source, "doc_test", baseline)[0]
    enriched = make_nodes(source, "doc_test", contextual)[0]
    assert "Supplier responsibilities" not in original.text
    assert "Supplier responsibilities" in enriched.text
    assert original.metadata == enriched.metadata
    provider = FakeProvider()
    assert fingerprint(baseline, provider) != fingerprint(contextual, provider)
    assert fingerprint(baseline, provider) == fingerprint(
        baseline.model_copy(update={"context_neighbors": False}), provider
    )
