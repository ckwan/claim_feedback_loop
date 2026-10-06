"""
A deliberately minimal in-memory vector store for claim history notes.

Why not ChromaDB/pgvector/a real vector DB here: claim history notes are a
handful of sentences per claim, and this project has, at most, a few hundred
claims. At that volume, an in-memory list with cosine similarity *is* the
right-sized solution — no persistence layer, no index-build time, no extra
infra to run. This class exists to demonstrate the interface a real vector
store would expose (`add`, `search`), so swapping the body for a Chroma/
pgvector-backed implementation later is a one-file change, not a rewrite of
ingestion.py or retriever.py.

At production scale (many thousands of claims, or notes long enough to need
chunking), this is exactly the point where you'd swap this class for a real
vector store with an approximate-nearest-neighbor index.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass


@dataclass
class VectorRecord:
    doc_id: str
    text: str
    org_id: str
    embedding: Counter


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._records: list[VectorRecord] = []

    def add(self, doc_id: str, text: str, org_id: str) -> None:
        self._records.append(
            VectorRecord(doc_id=doc_id, text=text, org_id=org_id, embedding=_embed(text))
        )

    def search(self, query: str, org_id: str, top_k: int = 3) -> list[tuple[str, float]]:
        """
        Returns up to top_k (doc_id, score) pairs, scoped to org_id — tenant
        isolation applies here exactly as it does everywhere else in this
        project; one org's claim history must never leak into another org's
        retrieval results.
        """
        query_vec = _embed(query)
        scored = [
            (record.doc_id, _cosine_similarity(query_vec, record.embedding))
            for record in self._records
            if record.org_id == org_id
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [pair for pair in scored if pair[1] > 0][:top_k]


def _embed(text: str) -> Counter:
    """
    Bag-of-words term-frequency vector. A stand-in for a real embedding
    model (e.g. an OpenAI/Anthropic/sentence-transformers embedding call).
    Good enough to demonstrate retrieval mechanics; a real deployment would
    embed with a trained model instead of raw word counts.
    """
    tokens = [t.strip(".,!?\"'").lower() for t in text.split()]
    return Counter(t for t in tokens if t)


def _cosine_similarity(a: Counter, b: Counter) -> float:
    shared = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in shared)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
