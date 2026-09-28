import hashlib
import re
from collections import defaultdict

from llama_index.core import Settings as LlamaSettings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

from docwiki.config import Settings
from docwiki.contracts import Evidence, Extraction
from docwiki.errors import AppError
from docwiki.evidence import context_text, evidence_text
from docwiki.tokens import tokens


def make_nodes(extraction: Extraction, doc_id: str, settings: Settings) -> list[TextNode]:
    LlamaSettings.tokenizer = tokens
    passages: list[Evidence] = []
    groups: dict[tuple, list[Evidence]] = defaultdict(list)
    for block_number, block in enumerate(extraction.blocks):
        block_id = block.block_id or f"block-{block_number}"
        prefix = ""
        texts = [block.text]
        if block.header:
            prefix = "Table columns: " + " | ".join(block.header) + "\n"
            texts = [
                " | ".join(f"{key}: {val}" for key, val in zip(block.header, row, strict=True))
                for row in block.rows
            ]
        elif block.kind == "json":
            prefix = f"Source record: {block.location.json_path}\n"
        overhead = len(tokens(prefix)) + len(tokens(context_text(block.context))) + 4
        if overhead >= settings.chunk_tokens - 30:
            raise AppError(
                "source_context_limit", "A source record has too much context to chunk safely."
            )
        splitter = SentenceSplitter(
            chunk_size=settings.chunk_tokens - overhead,
            chunk_overlap=min(settings.chunk_overlap, (settings.chunk_tokens - overhead) // 4),
            tokenizer=tokens,
            chunking_tokenizer_fn=lambda text: re.split(r"(?<=[.!?])\s+|\n\n+", text),
        )
        piece_number = 0
        for text in texts:
            for piece in splitter.split_text(text):
                source_id = (
                    "src_"
                    + hashlib.sha256(f"{doc_id}:{block_id}:{piece_number}".encode()).hexdigest()[
                        :24
                    ]
                )
                piece_number += 1
                evidence = Evidence(
                    source_id=source_id,
                    text=prefix + piece,
                    kind=block.kind,
                    location=block.location,
                    method=block.method,
                    block_id=block_id,
                    parent_id=block.parent_id,
                    group_id=block.group_id or block_id,
                    context=block.context,
                    header_location=block.header_location,
                    image_ref=block.image_ref,
                )
                passages.append(evidence)
                groups[(block.kind, block.location.page, evidence.group_id)].append(evidence)
                if len(passages) > settings.chunk_limit:
                    raise AppError("chunk_limit", "Document creates too many chunks.")
    if not passages:
        raise AppError("empty_document", "Document contains no indexable content.")
    for group in groups.values():
        for first, second in zip(group, group[1:], strict=False):
            first.next_id, second.previous_id = second.source_id, first.source_id
    nodes = []
    for evidence in passages:
        metadata = {"docwiki_document_id": doc_id, "source": evidence.model_dump_json()}
        relationships = {}
        for kind, ident in [
            (NodeRelationship.PREVIOUS, evidence.previous_id),
            (NodeRelationship.NEXT, evidence.next_id),
        ]:
            if ident:
                relationships[kind] = RelatedNodeInfo(node_id=ident)
        nodes.append(
            TextNode(
                id_=evidence.source_id,
                text=evidence_text(evidence) if settings.contextual_embeddings else evidence.text,
                metadata=metadata,
                excluded_embed_metadata_keys=list(metadata),
                excluded_llm_metadata_keys=list(metadata),
                relationships=relationships,
            )
        )
    return nodes
