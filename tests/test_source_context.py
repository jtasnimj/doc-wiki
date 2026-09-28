import asyncio
import sys

from docwiki.config import Settings
from docwiki.pdf import PDFExtractor


async def test_pdf_preserves_verified_heading_scope_and_table_header_provenance(tmp_path):
    path = tmp_path / "context.pdf"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "tests/make_context_pdf.py", str(path)
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
    assert table.header == ["Finding", "Requirement"]
    assert table.header_location.page == 1
    assert table.header_location.bbox != table.location.bbox
    assert [c.text for c in table.context] == ["Supplier responsibilities"]
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
