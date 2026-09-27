import asyncio
import contextvars
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.config import Settings as ChromaSettings
from llama_index.core import Settings as LlamaSettings
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import QueryBundle, TextNode
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.vector_stores.chroma import ChromaVectorStore
from pydantic import PrivateAttr

from docwiki.config import Settings
from docwiki.contracts import DocumentInfo, Evidence, Extraction
from docwiki.errors import AppError
from docwiki.providers import Provider
from docwiki.tokens import tokens

PARSER_VERSION = "page-blocks-v1"
CHUNKER_VERSION = "structure-v1"


class ControlledEmbedding(BaseEmbedding):
    """LlamaIndex embedding interface with no implicit synchronous provider calls."""

    _provider: Provider = PrivateAttr()

    def __init__(self, provider: Provider, model: str):
        super().__init__(model_name=model, embed_batch_size=32)
        self._provider = provider

    def _get_query_embedding(self, query):
        raise RuntimeError("Embeddings must be prepared asynchronously before local retrieval.")

    def _get_text_embedding(self, text):
        raise RuntimeError("Embeddings must be prepared asynchronously before local indexing.")

    async def _aget_query_embedding(self, query):
        return (await self._provider.embed([query]))[0]

    async def _aget_text_embedding(self, text):
        return (await self._provider.embed([text]))[0]

    async def _aget_text_embeddings(self, texts):
        return await self._provider.embed(texts)


def fingerprint(settings: Settings, provider: Provider) -> str:
    config = {
        "parser": PARSER_VERSION,
        "pymupdf": version("pymupdf"),
        "chunker": CHUNKER_VERSION,
        "chunk_tokens": settings.chunk_tokens,
        "overlap": settings.chunk_overlap,
        "embedding": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "vision": settings.vision_enabled,
        "vision_crops": settings.vision_crops,
        "vision_model": settings.generation_model,
        "provider": getattr(provider, "cache_namespace", "openai"),
        "llamaindex": version("llama-index-core"),
        "chroma": version("chromadb"),
        "limits": [
            settings.pdf_pages,
            settings.json_depth,
            settings.json_nodes,
            settings.extracted_bytes,
            settings.chunk_limit,
        ],
    }
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def make_nodes(extraction: Extraction, doc_id: str, settings: Settings) -> list[TextNode]:
    LlamaSettings.tokenizer = tokens
    nodes = []
    for block_number, block in enumerate(extraction.blocks):
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
            parent = next(
                (line for line in block.text.splitlines() if line.startswith("Parent fields:")), ""
            )
            if parent:
                prefix += parent + "\n"
        overhead = len(tokens(prefix))
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
                    + hashlib.sha256(
                        f"{doc_id}:{block_number}:{piece_number}".encode()
                    ).hexdigest()[:24]
                )
                piece_number += 1
                evidence = Evidence(
                    source_id=source_id,
                    text=prefix + piece,
                    kind=block.kind,
                    location=block.location,
                    method=block.method,
                    image_ref=block.image_ref,
                )
                metadata = {"docwiki_document_id": doc_id, "source": evidence.model_dump_json()}
                nodes.append(
                    TextNode(
                        id_=source_id,
                        text=evidence.text,
                        metadata=metadata,
                        excluded_embed_metadata_keys=list(metadata),
                        excluded_llm_metadata_keys=list(metadata),
                    )
                )
                if len(nodes) > settings.chunk_limit:
                    raise AppError("chunk_limit", "Document creates too many chunks.")
    if not nodes:
        raise AppError("empty_document", "Document contains no indexable content.")
    return nodes


class IndexStore:
    """One local store thread, LlamaIndex indexing/retrieval, and small ready manifests."""

    def __init__(self, settings: Settings, provider: Provider):
        self.settings = settings
        self.root = settings.data_dir
        self.embedder = ControlledEmbedding(provider, settings.embedding_model)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="docwiki-store")
        self.client: ClientAPI
        self.signature = fingerprint(settings, provider)

    async def run(self, fn, *args):
        ctx = contextvars.copy_context()
        future = asyncio.get_running_loop().run_in_executor(self.executor, ctx.run, fn, *args)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Local mutations finish before callers attempt cleanup; no deletion race.
            await future
            raise

    async def start(self):
        def initialize():
            (self.root / "documents").mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(
                path=str(self.root / "chroma"),
                settings=ChromaSettings(anonymized_telemetry=False),
            )

        await self.run(initialize)

    def document_id(self, raw: bytes) -> str:
        return "doc_" + hashlib.sha256(raw + self.signature.encode()).hexdigest()

    def directory(self, doc_id: str) -> Path:
        if not re.fullmatch(r"doc_[0-9a-f]{64}", doc_id):
            raise AppError("document_not_found", "Document was not found.", 404)
        return self.root / "documents" / doc_id

    def ready(self, doc_id: str) -> DocumentInfo | None:
        manifest = self.directory(doc_id) / "ready.json"
        if not manifest.exists():
            return None
        try:
            data = json.loads(manifest.read_text())
            if data["signature"] != self.signature:
                return None
            info = DocumentInfo.model_validate(data["info"])
            if (
                self.client.get_collection(doc_id, embedding_function=None).count()
                != info.chunk_count
            ):
                return None
            return info.model_copy(update={"cache_hit": True})
        except (ValueError, KeyError, chromadb.errors.ChromaError):
            return None

    def index(self, doc_id: str, nodes: list[TextNode]):
        try:
            self.client.delete_collection(doc_id)
        except chromadb.errors.NotFoundError:
            pass
        collection = self.client.create_collection(
            doc_id,
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )
        vector_store = ChromaVectorStore(chroma_collection=collection)
        VectorStoreIndex(
            nodes,
            embed_model=self.embedder,
            storage_context=StorageContext.from_defaults(vector_store=vector_store),
        )

    def mark_ready(self, info: DocumentInfo):
        path = self.directory(info.document_id) / "ready.json"
        # Single writer under the keyed lock. Readiness is the final small atomic write.
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"signature": self.signature, "info": info.model_dump()}))
        temp.replace(path)

    def remove_index(self, doc_id: str):
        try:
            self.client.delete_collection(doc_id)
        except chromadb.errors.NotFoundError:
            pass

    def retrieve(self, doc_id: str, question: str, embedding: list[float]) -> list[Evidence]:
        collection = self.client.get_collection(doc_id, embedding_function=None)
        index = VectorStoreIndex.from_vector_store(
            ChromaVectorStore(chroma_collection=collection), embed_model=self.embedder
        )
        retriever = index.as_retriever(
            similarity_top_k=self.settings.top_k,
            filters=MetadataFilters(
                filters=[MetadataFilter(key="docwiki_document_id", value=doc_id)]
            ),
        )
        results = retriever.retrieve(QueryBundle(query_str=question, embedding=embedding))
        evidence, budget, images = [], 0, 0
        for hit in results:
            item = Evidence.model_validate_json(hit.node.metadata["source"])
            cost = len(tokens(item.text))
            if budget + cost > self.settings.evidence_tokens:
                continue
            if item.image_ref:
                if images >= self.settings.answer_images:
                    continue
                images += 1
            budget += cost
            evidence.append(item)
        return evidence

    async def close(self):
        await asyncio.to_thread(self.executor.shutdown, wait=True)
