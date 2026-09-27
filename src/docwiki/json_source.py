import json
import math
from typing import Any

from docwiki.config import Settings
from docwiki.contracts import Extraction, Location, SourceBlock
from docwiki.errors import AppError


def parse_json(raw: bytes, settings: Settings) -> Any:
    # Count nesting before json.loads to avoid unbounded recursion in the decoder.
    depth, in_string, escaped = 0, False, False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                in_string = False
        elif char == 34:
            in_string = True
        elif char in (91, 123):
            depth += 1
            if depth > settings.json_depth:
                raise AppError("json_depth", "JSON nesting exceeds the configured limit.")
        elif char in (93, 125):
            depth -= 1

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("non-finite number")

    try:
        value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AppError(
            "invalid_json", "Supply valid UTF-8 JSON with unique keys and finite numbers."
        ) from exc
    stack, count = [value], 0
    while stack:
        item = stack.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise AppError("invalid_json", "JSON numbers must be finite.")
        count += 1
        if count > settings.json_nodes:
            raise AppError("json_nodes", "JSON contains too many values.")
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return value


def extract_json(raw: bytes, settings: Settings) -> Extraction:
    value = parse_json(raw, settings)
    if not isinstance(value, (dict, list)):
        raise AppError("json_source_shape", "A source document must be a JSON object or array.")
    blocks: list[SourceBlock] = []
    total_bytes = 0

    def informative(item):
        if isinstance(item, dict):
            return any(informative(v) for v in item.values())
        if isinstance(item, list):
            return any(informative(v) for v in item)
        return item is not None and (not isinstance(item, str) or bool(item.strip()))

    def visit(item, path, context):
        nonlocal total_bytes
        rendered = json.dumps(item, ensure_ascii=False, indent=2, allow_nan=False)
        if isinstance(item, list):
            for i, child in enumerate(item):
                visit(child, f"{path}[{i}]", context)
        elif isinstance(item, dict) and len(rendered) > 2400:
            scalars = {k: v for k, v in item.items() if not isinstance(v, (dict, list))}
            label = json.dumps(scalars, ensure_ascii=False)[:1500]
            for key, child in item.items():
                child_path = f"{path}[{json.dumps(key, ensure_ascii=False)}]"
                visit(child, child_path, (context + "\nParent fields: " + label)[-2000:])
        else:
            text = f"Path: {path}\n{context}\n{rendered}"
            total_bytes += len(text.encode())
            if total_bytes > settings.extracted_bytes or len(blocks) >= settings.chunk_limit:
                raise AppError("extracted_limit", "Normalized source exceeds the configured limit.")
            blocks.append(
                SourceBlock(
                    text=text,
                    kind="json",
                    location=Location(json_path=path),
                    method="json-record",
                )
            )

    if not informative(value):
        raise AppError("empty_document", "The source contains no informative content.")
    visit(value, "$", "")
    if sum(len(b.text.encode()) for b in blocks) > settings.extracted_bytes:
        raise AppError("extracted_limit", "Normalized source exceeds the configured size limit.")
    return Extraction(blocks=blocks)
