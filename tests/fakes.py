"""Deterministic test doubles, never a substitute for real-model quality results."""

import hashlib
import math
import re

from docwiki.contracts import ModelAnswer


class FakeProvider:
    cache_namespace = "offline-hash-v1"

    def __init__(self):
        self.embedding_calls = 0
        self.answer_calls = 0
        self.answers = {}

    async def embed(self, texts):
        self.embedding_calls += 1
        vectors = []
        for text in texts:
            vector = [0.0] * 64
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:2]) % 64
                vector[index] += 1
            norm = math.sqrt(sum(x * x for x in vector)) or 1
            vectors.append([x / norm for x in vector])
        return vectors

    async def answer(self, question, evidence, warnings):
        self.answer_calls += 1
        if question in self.answers:
            value = self.answers[question]
            if isinstance(value, Exception):
                raise value
            return value
        supporting = [e for e in evidence if "ExampleCloud" in e.text]
        if supporting:
            return ModelAnswer(
                answer="ExampleCloud.", status="answered", source_ids=[supporting[0].source_id]
            )
        return ModelAnswer(
            answer="Not found in the provided document.", status="not_found", source_ids=[]
        )

    async def describe(self, image):
        return "Primary region: US central. Backup region: US east. Visible labels only."

    async def close(self):
        pass
