"""The three ways to search claim notes, written as plain SQL.

All three filter by org_id inside the query. A search can never return another
tenant's rows, whatever the caller passes in.

  vector   nearest neighbours by meaning, using the pgvector <=> (cosine distance)
           operator and the HNSW index
  keyword  Postgres full text search: words are stemmed, matched with a GIN index and
           ranked with ts_rank
  hybrid   both of the above, merged with Reciprocal Rank Fusion in one query

Reciprocal Rank Fusion gives each result 1 / (k + rank) from every list it appears in
and adds them up. It uses only the order of each list, so it needs no tuning to make a
cosine distance and a text rank comparable, which is why it is the usual first choice.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

RRF_K = 60  # the constant from the original RRF paper. It softens the top ranks.
CANDIDATES = 20  # how many results each list contributes to the fusion


@dataclass
class Hit:
    claim_id: str
    chunk_index: int
    content: str
    score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None
    vector_distance: float | None = None  # cosine distance. 0 is identical.
    keyword_score: float | None = None


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


def tsquery_text(query: str) -> str | None:
    """Words joined with OR. Built from letters and digits only, so it cannot inject syntax.

    plainto_tsquery would AND every word and return nothing for a natural language
    question, so the query is built by hand and the ranking sorts out relevance.
    """
    words = [w for w in re.findall(r"[A-Za-z0-9]+", query.lower()) if len(w) > 1]
    return " | ".join(dict.fromkeys(words)) or None


def _tune_hnsw(db: Session) -> None:
    """Make filtered nearest neighbour search return enough rows.

    An HNSW index finds the nearest rows across the whole table and only then applies
    the WHERE clause. If most nearby rows belong to other organizations, a plain search
    can return fewer than LIMIT rows for this one. iterative_scan (pgvector 0.8+) keeps
    scanning until enough rows pass the filter. SET LOCAL lasts for this transaction.
    """
    try:
        with db.begin_nested():
            db.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
            db.execute(text("SET LOCAL hnsw.ef_search = 100"))
    except Exception:  # pgvector older than 0.8 has no such setting
        logger.info("hnsw.iterative_scan not available. Filtered results may be short.")


_EXCLUDE = "(CAST(:exclude AS text) IS NULL OR claim_id <> :exclude)"

VECTOR_SQL = f"""
SELECT claim_id, chunk_index, content,
       embedding <=> CAST(:qvec AS vector) AS distance,
       ROW_NUMBER() OVER (ORDER BY embedding <=> CAST(:qvec AS vector)) AS rank
FROM claim_chunks
WHERE org_id = :org AND embedding_model = :model AND {_EXCLUDE}
ORDER BY embedding <=> CAST(:qvec AS vector)
LIMIT :n
"""

KEYWORD_SQL = f"""
SELECT claim_id, chunk_index, content,
       ts_rank(tsv, q) AS score,
       ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, q) DESC, id) AS rank
FROM claim_chunks, to_tsquery('english', :tsq) AS q
WHERE org_id = :org AND tsv @@ q AND {_EXCLUDE}
ORDER BY score DESC, id
LIMIT :n
"""

HYBRID_SQL = f"""
WITH vector_hits AS MATERIALIZED (
    SELECT id, claim_id, chunk_index, content,
           embedding <=> CAST(:qvec AS vector) AS distance
    FROM claim_chunks
    WHERE org_id = :org AND embedding_model = :model AND {_EXCLUDE}
    ORDER BY embedding <=> CAST(:qvec AS vector)
    LIMIT :cand
),
vector_ranked AS (
    SELECT *, ROW_NUMBER() OVER (ORDER BY distance, id) AS rank FROM vector_hits
),
keyword_hits AS (
    SELECT id, claim_id, chunk_index, content, ts_rank(tsv, q) AS score
    FROM claim_chunks, to_tsquery('english', COALESCE(:tsq, '')) AS q
    WHERE org_id = :org AND tsv @@ q AND {_EXCLUDE}
    ORDER BY score DESC, id
    LIMIT :cand
),
keyword_ranked AS (
    SELECT *, ROW_NUMBER() OVER (ORDER BY score DESC, id) AS rank FROM keyword_hits
)
SELECT COALESCE(v.claim_id, k.claim_id)       AS claim_id,
       COALESCE(v.chunk_index, k.chunk_index) AS chunk_index,
       COALESCE(v.content, k.content)         AS content,
       COALESCE(1.0 / (:rrf_k + v.rank), 0) + COALESCE(1.0 / (:rrf_k + k.rank), 0) AS rrf,
       v.rank AS vrank, k.rank AS krank, v.distance, k.score
FROM vector_ranked v
FULL OUTER JOIN keyword_ranked k ON v.id = k.id
ORDER BY rrf DESC, claim_id
LIMIT :n
"""


def search_vector(db: Session, org_id: str, query_vec: list[float], model: str,
                  limit: int = 10, exclude_claim_id: str | None = None) -> list[Hit]:
    _tune_hnsw(db)
    rows = db.execute(
        text(VECTOR_SQL),
        {"qvec": vector_literal(query_vec), "org": org_id, "model": model,
         "exclude": exclude_claim_id, "n": limit},
    ).all()
    return [Hit(r.claim_id, r.chunk_index, r.content, 1.0 - r.distance,
                vector_rank=r.rank, vector_distance=r.distance) for r in rows]


def search_keyword(db: Session, org_id: str, query: str, limit: int = 10,
                   exclude_claim_id: str | None = None) -> list[Hit]:
    tsq = tsquery_text(query)
    if tsq is None:
        return []
    rows = db.execute(
        text(KEYWORD_SQL),
        {"tsq": tsq, "org": org_id, "exclude": exclude_claim_id, "n": limit},
    ).all()
    return [Hit(r.claim_id, r.chunk_index, r.content, r.score,
                keyword_rank=r.rank, keyword_score=r.score) for r in rows]


def search_hybrid(db: Session, org_id: str, query: str, query_vec: list[float], model: str,
                  limit: int = 10, exclude_claim_id: str | None = None,
                  candidates: int = CANDIDATES) -> list[Hit]:
    _tune_hnsw(db)
    rows = db.execute(
        text(HYBRID_SQL),
        {"qvec": vector_literal(query_vec), "tsq": tsquery_text(query), "org": org_id,
         "model": model, "exclude": exclude_claim_id, "n": limit, "cand": candidates,
         "rrf_k": RRF_K},
    ).all()
    return [Hit(r.claim_id, r.chunk_index, r.content, float(r.rrf),
                vector_rank=r.vrank, keyword_rank=r.krank,
                vector_distance=r.distance, keyword_score=r.score) for r in rows]
