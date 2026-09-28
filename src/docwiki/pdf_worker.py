"""Process-only PyMuPDF adapter. No imports from API, providers or vector storage."""

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pymupdf


def distinct_header_style(first, second, text_blocks) -> bool:
    """Only remove an internal header when typography distinguishes it from data."""

    def styles(rect):
        found = set()
        for block in text_blocks:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    box = pymupdf.Rect(span["bbox"])
                    if (box.tl + box.br) / 2 in pymupdf.Rect(rect):
                        found.add((bool(span["flags"] & 16), span["color"]))
        return found

    top, body = styles(first), styles(second)
    if not top or not body:
        return False
    return (any(bold for bold, _ in top) and not any(bold for bold, _ in body)) or (
        {color for _, color in top}.isdisjoint({color for _, color in body})
    )


def extract(path: str, options: dict) -> dict:
    blocks: list[dict[str, Any]] = []
    warnings, skipped, candidates, unknown_headers = [], [], [], []
    total = 0
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("encrypted_pdf")
        if not 0 < len(doc) <= options["pdf_pages"]:
            raise ValueError("pdf_page_limit")
        # Repeated images are usually logos/banners, not unique diagrams.
        image_pages: dict[int, set[int]] = {}
        for page in doc:
            for img in page.get_images():
                image_pages.setdefault(img[0], set()).add(page.number)
        for page in doc:
            page_blocks: list[dict[str, Any]] = []
            text_blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT, sort=True)["blocks"]
            sizes: Counter[float] = Counter()
            for text_block in text_blocks:
                for line in text_block.get("lines", []):
                    for span in line["spans"]:
                        sizes[round(span["size"], 1)] += len(span["text"].strip())
            body_size = sizes.most_common(1)[0][0] if sizes else 11
            drawings = [
                d for d in page.get_drawings() if d["rect"].get_area() < page.rect.get_area() * 0.85
            ]
            tables = page.find_tables(paths=drawings).tables
            rects = []
            for table in tables:
                rows = [[cell or "" for cell in row] for row in table.extract()]
                names = table.header.names
                plausible = all(name and len(name) < 80 and name.count("\n") <= 2 for name in names)
                reliable = plausible and (
                    table.header.external
                    or (
                        len(rows) > 1
                        and distinct_header_style(
                            table.rows[0].bbox, table.rows[1].bbox, text_blocks
                        )
                    )
                )
                headers = (
                    list(names) if reliable else [f"Column {i + 1}" for i in range(len(names))]
                )
                if reliable and not table.header.external:
                    rows = rows[1:]
                elif not reliable:
                    # Continuation pages often start with short data that looks like a
                    # header. Preserve every row unless there is positive header evidence.
                    unknown_headers.append(page.number + 1)
                if not rows or not any(cell.strip() for row in rows for cell in row):
                    continue
                rects.append(pymupdf.Rect(table.bbox))
                page_blocks.append(
                    dict(
                        text="\n".join(" | ".join(row) for row in [headers, *rows]),
                        kind="pdf",
                        location={"page": page.number + 1, "bbox": list(table.bbox)},
                        method="pymupdf-table",
                        header=headers,
                        header_location={
                            "page": page.number + 1,
                            "bbox": list(table.header.bbox),
                        }
                        if reliable
                        else None,
                        rows=rows,
                    )
                )
            for block in text_blocks:
                if block["type"] != 0:
                    continue
                lines = []
                included_spans = []
                for line in block["lines"]:
                    spans = []
                    for span in line["spans"]:
                        x0, y0, x1, y1 = span["bbox"]
                        if not any(pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2) in r for r in rects):
                            spans.append(span["text"])
                            included_spans.append(span)
                    if spans:
                        lines.append(" ".join(spans))
                text = "\n".join(lines).strip()
                if text:
                    heading = (
                        len(text) <= 120
                        and len(lines) <= 2
                        and not text.endswith((".", ";", ","))
                        and not text.startswith(("●", "•", "- "))
                        and all(span["size"] >= body_size + 1.5 for span in included_spans)
                        and 0.05 * page.rect.height < block["bbox"][1] < 0.9 * page.rect.height
                    )
                    page_blocks.append(
                        dict(
                            text=text,
                            kind="pdf",
                            location={"page": page.number + 1, "bbox": block["bbox"]},
                            method="pymupdf-text",
                            section=text if heading else None,
                        )
                    )
            page_blocks.sort(key=lambda b: (b["location"]["bbox"][1], b["location"]["bbox"][0]))
            active_heading = None
            for i, item in enumerate(page_blocks):
                item["block_id"] = f"page-{page.number + 1}-block-{i}"
                item["ordinal"] = len(blocks) + i
                if item.get("section"):
                    active_heading = item
                    item["group_id"] = item["block_id"]
                elif active_heading is not None:
                    x = item["location"]["bbox"][0]
                    heading_x = active_heading["location"]["bbox"][0]
                    if abs(x - heading_x) <= 24:
                        item["parent_id"] = active_heading["block_id"]
                        item["group_id"] = active_heading["block_id"]
                        item["context"] = [
                            {
                                "block_id": active_heading["block_id"],
                                "role": "heading",
                                "text": active_heading["text"],
                                "location": active_heading["location"],
                            }
                        ]
                if item.get("rows"):
                    item["group_id"] = item["block_id"]
            usable = sum(len(b["text"].strip()) for b in page_blocks)
            if usable < 30:
                skipped.append(page.number + 1)
            # Text density alone misses diagrams embedded in narrative pages.
            visual_rects = []
            for img in page.get_images():
                if len(image_pages[img[0]]) == 1:
                    visual_rects.extend(page.get_image_rects(img[0]))
            if drawings:
                body_drawings = [
                    d
                    for d in drawings
                    if d["rect"].y0 > page.rect.height * 0.1
                    and d["rect"].y1 < page.rect.height * 0.9
                ]
                if body_drawings:
                    visual_rects.extend(page.cluster_drawings(drawings=body_drawings))
            visual_rects = [
                r
                for r in visual_rects
                if page.rect.get_area() * 0.07 < r.get_area() < page.rect.get_area() * 0.85
                and not any((r & t).get_area() > r.get_area() * 0.5 for t in rects)
            ]
            if visual_rects:
                # One page-level crop preserves relationships between vector/raster parts.
                region = pymupdf.Rect(visual_rects[0])
                for rect in visual_rects[1:]:
                    region |= rect
                candidates.append({"page": page.number + 1, "bbox": list(region & page.rect)})
            blocks.extend(page_blocks)
            total += sum(len(b["text"].encode()) for b in page_blocks)
            if total > options["extracted_bytes"]:
                raise ValueError("extracted_limit")
        if not blocks:
            raise ValueError("no_usable_text")
        if skipped:
            warnings.append(
                "Limited text coverage on PDF pages: "
                + ", ".join(map(str, skipped))
                + ". OCR is disabled."
            )
        if unknown_headers:
            warnings.append(
                "No reliable table headers on pages "
                + ", ".join(map(str, sorted(set(unknown_headers))))
                + "; positional columns retained without cross-page stitching."
            )
        if candidates:
            warnings.append(
                "Potential figure content on PDF pages: "
                + ", ".join(str(c["page"]) for c in candidates)
                + ". Text/table extraction may omit visual relationships."
            )
        return dict(
            blocks=blocks,
            page_count=len(doc),
            warnings=warnings,
            visual_candidates=candidates,
            skipped_pages=skipped,
        )


def render(path: str, options: dict) -> dict:
    outputs = []
    with pymupdf.open(path) as doc:
        for i, loc in enumerate(options["locations"][:3]):
            page = doc[loc["page"] - 1]
            clip = pymupdf.Rect(loc["bbox"]) if loc.get("bbox") else page.rect
            clip &= page.rect
            scale = min(2, (4_000_000 / max(clip.get_area(), 1)) ** 0.5)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
            dest = Path(options["output_dir"]) / f"crop-{i}.png"
            pix.save(dest)
            outputs.append({"location": loc, "path": str(dest)})
    return {"images": outputs}


if __name__ == "__main__":
    source, destination, raw_options = sys.argv[1:]
    options = json.loads(raw_options)
    try:
        result = render(source, options) if options.get("render") else extract(source, options)
    except ValueError as exc:
        known = {"encrypted_pdf", "pdf_page_limit", "extracted_limit", "no_usable_text"}
        result = {"error": str(exc) if str(exc) in known else "invalid_pdf"}
    except Exception:
        result = {"error": "invalid_pdf"}
    Path(destination).write_text(json.dumps(result), encoding="utf-8")
