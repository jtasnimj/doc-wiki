from docwiki.config import Settings
from docwiki.json_source import extract_json
from docwiki.retrieval import IndexStore, make_nodes
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
