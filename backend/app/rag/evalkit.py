"""Measuring retrieval quality.

Given queries with known relevant claims, how often does each search method put a
relevant claim near the top? Metrics:

  recall@k   of the claims that are relevant, the share found in the top k
  MRR        mean reciprocal rank: 1 / (rank of the first relevant result), else 0.
             1.0 means the first result is always relevant.

Methods compared: keyword, vector, hybrid, and hybrid with LLM reranking.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.rag.embeddings import Embedder
from app.rag.indexing import index_claim
from app.rag.retriever import retrieve
from app.rag.rerank import Reranker

DATA = Path(__file__).resolve().parents[2] / "data" / "retrieval_eval.json"
METHODS = ("keyword", "vector", "hybrid", "hybrid+rerank")


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str], k: int = 5) -> float:
    for i, claim_id in enumerate(ranked[:k], start=1):
        if claim_id in relevant:
            return 1.0 / i
    return 0.0


def load_dataset(path: Path = DATA) -> dict:
    return json.loads(path.read_text())


def load_corpus(db: Session, org_id: str, claims: list[dict], embedder: Embedder) -> dict[str, str]:
    """Insert the synthetic claims into one organization and index them.

    Returns a map from the dataset's id (c01) to the real claim id.
    """
    ids = {}
    for c in claims:
        row = models.Claim(org_id=org_id, claimant_name=c["id"], amount=1000, history_notes=c["text"])
        db.add(row)
        db.flush()
        ids[c["id"]] = row.id
    db.commit()
    for real_id in ids.values():
        index_claim(db, db.get(models.Claim, real_id), embedder)
    return ids


def run_eval(db: Session, org_id: str, dataset: dict, ids: dict[str, str], embedder: Embedder,
             methods: tuple[str, ...] = METHODS, reranker: Reranker | None = None, k: int = 5) -> dict:
    """Return metrics per method, overall and per query kind."""
    back = {real: short for short, real in ids.items()}
    rows: dict[str, dict[str, list]] = {m: defaultdict(list) for m in methods}
    for q in dataset["queries"]:
        relevant = set(q["relevant"])
        for method in methods:
            mode, rerank = (method.split("+")[0], "+" in method)
            start = time.perf_counter()
            found = retrieve(db, org_id, q["text"], mode=mode, top_k=k, rerank=rerank,
                             embedder=embedder, reranker=reranker)
            ms = (time.perf_counter() - start) * 1000
            ranked = [back[h.claim_id] for h in found.hits]
            for bucket in ("all", q["kind"]):
                rows[method][bucket].append(
                    (recall_at_k(ranked, relevant, 3), recall_at_k(ranked, relevant, 5),
                     reciprocal_rank(ranked, relevant, k), ms)
                )
    out = {}
    for method, buckets in rows.items():
        out[method] = {}
        for bucket, vals in buckets.items():
            n = len(vals)
            out[method][bucket] = {
                "queries": n,
                "recall@3": round(sum(v[0] for v in vals) / n, 3),
                "recall@5": round(sum(v[1] for v in vals) / n, 3),
                "mrr": round(sum(v[2] for v in vals) / n, 3),
                "avg_ms": round(sum(v[3] for v in vals) / n, 1),
            }
    return out


def table(results: dict) -> str:
    lines = ["| Method | Queries | recall@3 | recall@5 | MRR | avg ms |", "|---|---|---|---|---|---|"]
    for bucket in ("all", "paraphrase", "exact"):
        for method, buckets in results.items():
            if bucket in buckets:
                r = buckets[bucket]
                label = f"{method} ({bucket})" if bucket != "all" else method
                lines.append(f"| {label} | {r['queries']} | {r['recall@3']} | {r['recall@5']} | {r['mrr']} | {r['avg_ms']} |")
    return "\n".join(lines)
