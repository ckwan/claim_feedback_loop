import math

import httpx
import pytest

from app.models import EMBEDDING_DIM
from app.rag.embeddings import EmbeddingError, HashEmbedder, OllamaEmbedder, get_embedder, tokenize


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_hash_embedder_is_deterministic_and_normalised():
    e = HashEmbedder()
    v1, v2 = e.embed_query("burst pipe in the kitchen"), e.embed_query("burst pipe in the kitchen")
    assert v1 == v2
    assert len(v1) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, rel_tol=1e-6)


def test_hash_embedder_prefers_shared_words():
    e = HashEmbedder()
    q = e.embed_query("kitchen pipe burst")
    close = e.embed_documents(["A pipe burst in the kitchen."])[0]
    far = e.embed_documents(["Laptop stolen from a parked car."])[0]
    assert cosine(q, close) > cosine(q, far)


def test_hash_embedder_handles_empty_text():
    assert not any(HashEmbedder().embed_query(""))


def test_tokenize_drops_stop_words_and_simple_endings():
    assert tokenize("The pipes were flooding") == ["pipe", "flood"]
    assert "the" not in tokenize("the pipe")
    assert tokenize("flooded") == tokenize("flooding")


def test_default_embedder_is_the_offline_stub(monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    assert isinstance(get_embedder(), HashEmbedder)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    assert isinstance(get_embedder(), OllamaEmbedder)


def ollama(handler, model="nomic-embed-text"):
    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    return OllamaEmbedder(model=model, client=client)


def test_ollama_embedder_sends_task_prefixes_for_nomic():
    seen = []

    def handler(request):
        import json
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        return httpx.Response(200, json={"embeddings": [[0.1] * EMBEDDING_DIM for _ in body["input"]]})

    e = ollama(handler)
    e.embed_documents(["a note", "another"])
    e.embed_query("what happened")
    assert seen[0][0] == "/api/embed"
    assert seen[0][1]["model"] == "nomic-embed-text"
    assert seen[0][1]["input"] == ["search_document: a note", "search_document: another"]
    assert seen[1][1]["input"] == ["search_query: what happened"]
    assert e.name == "ollama:nomic-embed-text"


def test_ollama_embedder_skips_prefix_for_other_models():
    sent = []

    def handler(request):
        import json
        sent.append(json.loads(request.content)["input"])
        return httpx.Response(200, json={"embeddings": [[0.0] * EMBEDDING_DIM]})

    ollama(handler, model="bge-m3").embed_query("hello")
    assert sent == [["hello"]]


def test_wrong_vector_size_is_a_clear_error():
    e = ollama(lambda r: httpx.Response(200, json={"embeddings": [[0.0] * 384]}))
    with pytest.raises(EmbeddingError, match="768"):
        e.embed_query("x")


def test_http_failure_becomes_embedding_error_without_leaking_text():
    e = ollama(lambda r: httpx.Response(500))
    with pytest.raises(EmbeddingError) as err:
        e.embed_documents(["secret claim note"])
    assert "secret claim note" not in str(err.value)


def test_empty_document_list_makes_no_request():
    def handler(request):
        raise AssertionError("no request expected")

    assert ollama(handler).embed_documents([]) == []
