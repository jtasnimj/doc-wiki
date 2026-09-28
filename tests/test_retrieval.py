from doc_wiki.config import Settings
from doc_wiki.json_source import extract_json
from doc_wiki.retrieval import IndexStore, make_nodes
from tests.fakes import FakeProvider


async def test_real_llamaindex_chroma_round_trip_and_document_isolation(tmp_path):
    provider = FakeProvider()
    settings = Settings(data_dir=tmp_path, embedding_dimensions=64)
    store = IndexStore(settings, provider)
    await store.start()
    try:
        for raw in [b'{"cloud":"ExampleCloud"}', b'{"cloud":"TemptingWrongCloud"}']:
            doc_id = store.document_id(raw)
            nodes = make_nodes(extract_json(raw, settings), doc_id, settings)
            vectors = await store.embedder.aget_text_embedding_batch([n.text for n in nodes])
            for node, vector in zip(nodes, vectors, strict=True):
                node.embedding = vector
            await store.run(store.index, doc_id, nodes)
        wanted = store.document_id(b'{"cloud":"ExampleCloud"}')
        vector = await store.embedder.aget_query_embedding("Which cloud?")
        evidence = await store.run(store.retrieve, wanted, "Which cloud?", vector)
        assert evidence and all("TemptingWrongCloud" not in e.text for e in evidence)
        assert "ExampleCloud" in evidence[0].text
        assert evidence[0].location.json_path == "$"
    finally:
        await store.close()


async def test_dense_seed_expands_only_to_its_verified_neighbors(tmp_path):
    from doc_wiki.contracts import Extraction, Location, SourceBlock
    from doc_wiki.evidence import evidence_text
    from doc_wiki.tokens import tokens

    settings = Settings(data_dir=tmp_path, embedding_dimensions=64, top_k=1)
    store = IndexStore(settings, FakeProvider())
    await store.start()
    try:
        blocks = [
            SourceBlock(
                text=text,
                kind="pdf",
                method="pymupdf-text",
                location=Location(page=1, bbox=(0, i * 30, 200, i * 30 + 20)),
                block_id=str(i),
                group_id="section-a" if i < 3 else "section-b",
            )
            for i, text in enumerate(
                [
                    "A policy exists.",
                    "The policy is published.",
                    "Staff and contractors can read it.",
                    "Unrelated suppliers.",
                ]
            )
        ]
        doc_id = store.document_id(b"context document")
        nodes = make_nodes(Extraction(blocks=blocks), doc_id, settings)
        for i, node in enumerate(nodes):
            node.embedding = ([1.0, 0.0] if i == 1 else [0.0, 1.0]) + [0.0] * 62
        await store.run(store.index, doc_id, nodes)
        hits = await store.run(
            store.retrieve, doc_id, "Who can read the policy?", [1.0, 0.0] + [0.0] * 62
        )
        assert hits[0].text == "The policy is published."
        assert [hit.retrieval_role for hit in hits] == ["seed", "context", "context"]
        assert any("contractors" in e.text for e in hits)
        assert not any("Unrelated" in e.text for e in hits)
        assert len({e.source_id for e in hits}) == len(hits)
        assert sum(len(tokens(evidence_text(e))) for e in hits) <= settings.evidence_tokens
    finally:
        await store.close()


async def test_context_cannot_displace_dense_seeds_and_links_survive_restart(tmp_path):
    from doc_wiki.contracts import Extraction, Location, SourceBlock
    from doc_wiki.tokens import tokens

    texts = ["Extra context " * 30, "Primary fact.", "Another relevant fact."]
    budget = sum(len(tokens(text)) for text in texts[1:])
    settings = Settings(data_dir=tmp_path, embedding_dimensions=64, top_k=2, evidence_tokens=budget)
    provider = FakeProvider()
    store = IndexStore(settings, provider)
    await store.start()
    doc_id = store.document_id(b"seeds")
    try:
        nodes = make_nodes(
            Extraction(
                blocks=[
                    SourceBlock(
                        text=text,
                        kind="pdf",
                        method="pymupdf-text",
                        location=Location(page=1, bbox=(0, i * 20, 100, i * 20 + 10)),
                        block_id=str(i),
                        group_id="one" if i < 2 else "two",
                    )
                    for i, text in enumerate(texts)
                ]
            ),
            doc_id,
            settings,
        )
        for node, pair in zip(nodes, [[0.0, 1.0], [1.0, 0.0], [0.99, 0.01]], strict=True):
            node.embedding = pair + [0.0] * 62
        await store.run(store.index, doc_id, nodes)
        hits = await store.run(store.retrieve, doc_id, "facts", [1.0, 0.0] + [0.0] * 62)
        assert [e.text for e in hits] == texts[1:]
    finally:
        await store.close()
    resumed = IndexStore(settings.model_copy(update={"evidence_tokens": 1000}), provider)
    await resumed.start()
    try:
        hits = await resumed.run(resumed.retrieve, doc_id, "facts", [1.0, 0.0] + [0.0] * 62)
        assert [e.text for e in hits[:2]] == texts[1:]
        assert hits[2].text == texts[0].strip()
        assert provider.embedding_calls == 0
    finally:
        await resumed.close()
