import asyncio
import contextvars
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.config import Settings as ChromaSettings
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import QueryBundle, TextNode
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.vector_stores.chroma import ChromaVectorStore
from pydantic import PrivateAttr

from doc_wiki.config import Settings
from doc_wiki.contracts import DocumentInfo, Evidence
from doc_wiki.errors import AppError
from doc_wiki.evidence import evidence_text
from doc_wiki.nodes import make_nodes as make_nodes
from doc_wiki.observability import event
from doc_wiki.providers import Provider
from doc_wiki.tokens import tokens

PARSER_VERSION = "source-context-v4"
CHUNKER_VERSION = "context-links-v2"


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
        "contextual_embeddings": settings.contextual_embeddings,
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


class IndexStore:
    """One local store thread, LlamaIndex indexing/retrieval, and small ready manifests."""

    def __init__(self, settings: Settings, provider: Provider):
        self.settings = settings
        self.root = settings.data_dir
        self.embedder = ControlledEmbedding(provider, settings.embedding_model)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="docwiki-store")
        self.client: ClientAPI
        self.signature = fingerprint(settings, provider)

    async def run(self, fn, *args, finish_on_cancel=True):
        ctx = contextvars.copy_context()
        future = asyncio.get_running_loop().run_in_executor(self.executor, ctx.run, fn, *args)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if finish_on_cancel:
                # Mutations finish before cleanup; reads must not delay partial responses.
                await future
            else:
                future.cancel()
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
        started = time.monotonic()
        collection = self.client.get_collection(doc_id, embedding_function=None)
        vector_store = ChromaVectorStore(chroma_collection=collection)
        index = VectorStoreIndex.from_vector_store(vector_store, embed_model=self.embedder)
        retriever = index.as_retriever(
            similarity_top_k=self.settings.top_k,
            filters=MetadataFilters(
                filters=[MetadataFilter(key="docwiki_document_id", value=doc_id)]
            ),
        )
        results = retriever.retrieve(QueryBundle(query_str=question, embedding=embedding))
        evidence: list[Evidence] = []
        budget, images = 0, 0
        seen = set()

        def include(item: Evidence):
            nonlocal budget, images
            cost = len(tokens(evidence_text(item)))
            if item.source_id in seen or budget + cost > self.settings.evidence_tokens:
                return
            if item.image_ref:
                if images >= self.settings.answer_images:
                    return
                images += 1
            budget += cost
            seen.add(item.source_id)
            evidence.append(item)

        for hit in results:
            item = Evidence.model_validate_json(hit.node.metadata["source"])
            include(item)
        seeds = list(evidence)
        if self.settings.context_neighbors:
            ids = list(
                dict.fromkeys(
                    ident
                    for seed in seeds
                    for ident in (seed.previous_id, seed.next_id)
                    if ident and ident not in seen
                )
            )
            neighbors = {}
            if ids:
                for node in vector_store.get_nodes(ids):
                    if node.metadata.get("docwiki_document_id") == doc_id:
                        item = Evidence.model_validate_json(node.metadata["source"])
                        neighbors[item.source_id] = item
            for seed in seeds:
                for ident in (seed.previous_id, seed.next_id):
                    neighbor = neighbors.get(ident) if ident else None
                    if neighbor is not None:
                        if (
                            seed.group_id is not None
                            and neighbor.group_id == seed.group_id
                            and neighbor.kind == seed.kind
                            and neighbor.location.page == seed.location.page
                        ):
                            include(neighbor.model_copy(update={"retrieval_role": "context"}))
        event(
            "retrieval_complete",
            document_id=doc_id,
            seed_count=len(seeds),
            context_count=len(evidence) - len(seeds),
            evidence_count=len(evidence),
            evidence_tokens=budget,
            latency_ms=round((time.monotonic() - started) * 1000),
        )
        return evidence

    async def close(self):
        if hasattr(self, "client"):
            # Chroma 1.5 exposes close on the concrete client, ahead of ClientAPI's typing.
            await self.run(self.client.close)  # type: ignore[attr-defined]
        await asyncio.to_thread(self.executor.shutdown, wait=True)
