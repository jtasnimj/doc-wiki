from docwiki.contracts import Evidence, Location, SourceContext


def context_text(context: list[SourceContext]) -> str:
    parts = []
    for item in context:
        location = item.location.json_path or f"page {item.location.page}"
        parts.append(f"Source {item.role} ({location}): {item.text}")
        if item.omitted_values:
            parts.append("Context omits some values; consult the original record at this path.")
    return "\n".join(parts)


def evidence_text(item: Evidence) -> str:
    context = context_text(item.context)
    return f"{context}\nPassage:\n{item.text}" if context else item.text


def evidence_locations(item: Evidence) -> list[Location]:
    locations = [item.location]
    for location in [item.header_location, *(c.location for c in item.context)]:
        if location is not None and location not in locations:
            locations.append(location)
    return locations
