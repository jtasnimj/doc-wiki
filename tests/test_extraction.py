import json

import pytest

from docwiki.config import Settings
from docwiki.errors import AppError
from docwiki.json_source import extract_json, parse_json


def test_json_records_preserve_values_context_and_paths():
    source = {"hosting": [{"region": "west", "enabled": False, "count": 0, "backup": None}]}
    extraction = extract_json(json.dumps(source).encode(), Settings())
    content = "\n".join(b.text for b in extraction.blocks)
    for text in ['"hosting"', '"enabled": false', '"count": 0', '"backup": null']:
        assert text in content
    assert extraction.blocks[0].location.json_path == "$"
    source = [{"name": "alpha", "description": "x " * 3000}]
    blocks = extract_json(json.dumps(source).encode(), Settings()).blocks
    assert any(b.location.json_path == '$[0]["description"]' for b in blocks)
    assert all("alpha" in b.text for b in blocks)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b"{bad}", b"{}", b"[]", b"null"])
def test_invalid_or_empty_json_sources(raw):
    with pytest.raises(AppError):
        extract_json(raw, Settings())


def test_json_bounds_and_false_zero_are_informative():
    with pytest.raises(AppError, match="nesting"):
        parse_json(b"[[[0]]]", Settings(json_depth=2))
    with pytest.raises(AppError, match="many values"):
        parse_json(b"[1,2,3]", Settings(json_nodes=2))
    assert extract_json(b'{"enabled":false,"count":0}', Settings()).blocks


async def test_pdf_worker_preserves_page_table_relationships(tmp_path):
    # This fixture is authored in a subprocess: no PyMuPDF objects enter the API process.
    import asyncio
    import sys

    from docwiki.pdf import PDFExtractor

    path = tmp_path / "table.pdf"
    process = await asyncio.create_subprocess_exec(sys.executable, "tests/make_pdf.py", str(path))
    assert await process.wait() == 0
    result = await PDFExtractor(Settings()).extract(path)
    assert result.page_count == 2
    assert all(b.location.page in (1, 2) and b.location.bbox for b in result.blocks)
    tables = [b for b in result.blocks if b.method == "pymupdf-table"]
    assert tables and tables[0].header == ["Control", "Result"]
    assert ["CC1", "Approved"] in tables[0].rows
    assert "Second page" in " ".join(b.text for b in result.blocks if b.location.page == 2)
