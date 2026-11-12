"""Turning text into vectors.

An embedding model maps text to a list of numbers so that texts with similar meaning
end up close together. Two implementations:

  * OllamaEmbedder: a real model run locally by Ollama (free). The default choice is
    nomic-embed-text, which produces 768 numbers per text.
  * HashEmbedder: a deterministic stand in with no model behind it. It hashes words
    into buckets, so it matches shared words and nothing more. It exists so tests and
    a first run work with no setup. It does NOT understand meaning, and results from
    it should not be used to judge retrieval quality.

Pick one with EMBEDDING_PROVIDER=ollama or stub (stub is the default).
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from typing import Protocol

from app.models import EMBEDDING_DIM

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    name: str  # stored with every vector, so vectors from different models never mix

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 timeout: float = 60.0, client=None):
        import httpx

        self.model = model or os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
        self.name = f"ollama:{self.model}"
        self._base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._client = client or httpx.Client(base_url=self._base_url, timeout=timeout)

    # nomic-embed-text is trained with a task prefix. Leaving it off lowers quality.
    def _prefix(self, kind: str) -> str:
        return f"{kind}: " if "nomic" in self.model else ""

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        try:
            response = self._client.post("/api/embed", json={"model": self.model, "input": inputs})
            response.raise_for_status()
            vectors = response.json()["embeddings"]
        except Exception as exc:  # network, missing model, bad JSON
            raise EmbeddingError(f"Ollama embedding call failed: {type(exc).__name__}") from exc
        if len(vectors) != len(inputs) or any(len(v) != EMBEDDING_DIM for v in vectors):
            raise EmbeddingError(
                f"Expected {len(inputs)} vectors of {EMBEDDING_DIM} numbers. A model with a "
                "different size needs a migration to change the column."
            )
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self._prefix("search_document") + t for t in texts]) if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self._prefix("search_query") + text])[0]


_STOP = frozenset(
    "a an and are as at be by for from has have in is it of on or that the their this to was were with".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase words with stop words and simple endings removed."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        if w in _STOP or len(w) < 2:
            continue
        for suffix in ("ing", "ed", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[: -len(suffix)]
                break
        out.append(w)
    return out


class HashEmbedder:
    name = "hash-768"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * EMBEDDING_DIM
        tokens = tokenize(text)
        for feature in tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]:
            digest = hashlib.sha256(feature.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
            vec[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm else vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def get_embedder() -> Embedder:
    if os.getenv("EMBEDDING_PROVIDER", "stub") == "ollama":
        return OllamaEmbedder()
    return HashEmbedder()
