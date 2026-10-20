import pytest

from app.models import Organization
from app.rag import evalkit
from app.rag.embeddings import HashEmbedder


def test_recall_at_k():
    assert evalkit.recall_at_k(["a", "b", "c"], {"a", "c"}, 3) == 1.0
    assert evalkit.recall_at_k(["a", "b", "c"], {"a", "c"}, 2) == 0.5
    assert evalkit.recall_at_k(["x"], {"a"}, 5) == 0.0
    assert evalkit.recall_at_k(["a"], set(), 5) == 0.0


def test_reciprocal_rank():
    assert evalkit.reciprocal_rank(["a", "b"], {"a"}) == 1.0
    assert evalkit.reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)
    assert evalkit.reciprocal_rank(["x", "y"], {"a"}) == 0.0
    assert evalkit.reciprocal_rank(["x", "x", "x", "x", "x", "a"], {"a"}, k=5) == 0.0  # beyond k


def test_dataset_is_consistent():
    data = evalkit.load_dataset()
    ids = [c["id"] for c in data["claims"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 25
    assert len({q["id"] for q in data["queries"]}) == len(data["queries"])
    for q in data["queries"]:
        assert q["kind"] in {"paraphrase", "exact"}
        assert q["relevant"] and set(q["relevant"]) <= set(ids), q["id"]
    kinds = {q["kind"] for q in data["queries"]}
    assert kinds == {"paraphrase", "exact"}  # both are needed to compare the methods


def test_exact_queries_literally_appear_in_their_relevant_claims():
    """If this fails a label is wrong, since an exact query is a phrase from the note."""
    data = evalkit.load_dataset()
    text = {c["id"]: c["text"].lower() for c in data["claims"]}
    for q in data["queries"]:
        if q["kind"] == "exact":
            assert all(q["text"].lower() in text[r] for r in q["relevant"]), q["id"]


def test_harness_runs_every_method_on_postgres(pg_db):
    org = Organization(name="eval")
    pg_db.add(org)
    pg_db.commit()
    data = evalkit.load_dataset()
    e = HashEmbedder()
    ids = evalkit.load_corpus(pg_db, org.id, data["claims"], e)
    results = evalkit.run_eval(pg_db, org.id, data, ids, e)

    assert set(results) == set(evalkit.METHODS)
    for method in results.values():
        assert set(method) == {"all", "paraphrase", "exact"}
        assert method["all"]["queries"] == len(data["queries"])
        assert 0 <= method["all"]["mrr"] <= 1
    # Exact phrases are the easy case for keyword search, so a drop here means a bug.
    assert results["keyword"]["exact"]["recall@5"] == 1.0
    table = evalkit.table(results)
    assert "hybrid+rerank" in table and "recall@3" in table
