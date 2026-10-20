"""Retrieval pipeline and the cited history summary.

    query -> embed -> search (vector, keyword or hybrid) -> [rerank] -> top results

Everything is scoped to one organization inside the SQL. Reranking is optional and
never removes results. The summary built on top must cite its sources, and citations
that point at nothing are removed.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.agents.llm_client import get_llm_client
from app.database import session_is_postgres
from app.rag import search as sql_search
from app.rag.embeddings import Embedder, get_embedder
from app.rag.rerank import LLMReranker, Reranker
from app.safety import UNTRUSTED_NOTICE, clean_text, neutralize_tags

logger = logging.getLogger(__name__)

MODES = ("hybrid", "vector", "keyword")
RERANK_POOL = 10  # candidates handed to the reranker


class SearchUnavailable(Exception):
    """Search needs Postgres with the pgvector extension."""


@dataclass
class ResultHit:
    claim_id: str
    claimant_name: str
    amount: float
    status: str
    snippet: str
    score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None


@dataclass
class SearchResult:
    query: str
    mode: str
    reranked: bool
    embedding_model: str
    hits: list[ResultHit] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def retrieve(
    db: Session,
    org_id: str,
    query: str,
    *,
    mode: str = "hybrid",
    top_k: int = 5,
    rerank: bool = False,
    exclude_claim_id: str | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> SearchResult:
    if not session_is_postgres(db):
        raise SearchUnavailable("Search needs Postgres with pgvector. Run `docker compose up`.")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")

    query = clean_text(query, 500)
    embedder = embedder or get_embedder()
    timings: dict[str, float] = {}
    pool = max(top_k, RERANK_POOL) if rerank else top_k

    qvec: list[float] = []
    if mode in ("hybrid", "vector"):
        t = time.perf_counter()
        qvec = embedder.embed_query(query)
        timings["embed"] = _ms(t)

    t = time.perf_counter()
    if mode == "vector":
        raw = sql_search.search_vector(db, org_id, qvec, embedder.name, pool * 2, exclude_claim_id)
    elif mode == "keyword":
        raw = sql_search.search_keyword(db, org_id, query, pool * 2, exclude_claim_id)
    else:
        raw = sql_search.search_hybrid(db, org_id, query, qvec, embedder.name, pool * 2, exclude_claim_id)
    timings["search"] = _ms(t)

    # One result per claim: the best chunk. Claims are what gets cited.
    best: dict[str, sql_search.Hit] = {}
    for h in raw:
        best.setdefault(h.claim_id, h)
    hits = list(best.values())[:pool]

    claims = {
        c.id: c
        for c in db.execute(
            select(models.Claim).where(
                models.Claim.org_id == org_id,  # again, on purpose
                models.Claim.id.in_([h.claim_id for h in hits]),
            )
        ).scalars()
    }
    results = [
        ResultHit(
            claim_id=h.claim_id,
            claimant_name=claims[h.claim_id].claimant_name,
            amount=claims[h.claim_id].amount,
            status=claims[h.claim_id].status.value,
            snippet=h.content,
            score=round(h.score, 5),
            vector_rank=h.vector_rank,
            keyword_rank=h.keyword_rank,
        )
        for h in hits
        if h.claim_id in claims
    ]

    reranked = False
    if rerank and len(results) > 1:
        t = time.perf_counter()
        order = (reranker or LLMReranker()).rerank(query, [r.snippet for r in results])
        timings["rerank"] = _ms(t)
        reranked = any(score is not None for _, score in order)
        results = [
            ResultHit(**{**results[i].__dict__, "rerank_score": score}) for i, score in order
        ]

    return SearchResult(query, mode, reranked, embedder.name, results[:top_k], timings)


# --- cited history summary ---------------------------------------------------------

SUMMARY_PROMPT = """Summarize what these sources suggest about how to handle the current claim, in 2 to 3 sentences. \
Use only facts stated in the sources. After each fact, cite the source it came from like [1]. \
If no source is relevant, say so and do not cite. {notice}

<history>
{current}
</history>

{sources}"""


@dataclass
class HistorySummary:
    summary: str
    sources: list[ResultHit]
    grounded: bool  # at least one valid citation
    removed_citations: list[int] = field(default_factory=list)


def check_citations(summary: str, source_count: int) -> tuple[str, list[int], bool]:
    """Remove [n] markers that point at a source that does not exist."""
    removed: list[int] = []

    def fix(match: re.Match) -> str:
        n = int(match.group(1))
        if 1 <= n <= source_count:
            return match.group(0)
        removed.append(n)
        return ""

    cleaned = re.sub(r"\[(\d+)\]", fix, summary)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, removed, bool(re.search(r"\[\d+\]", cleaned))


def summarize_history(db: Session, claim: models.Claim, *, embedder: Embedder | None = None,
                      reranker: Reranker | None = None, rerank: bool = False) -> HistorySummary:
    query = claim.history_notes or ""
    found = retrieve(db, claim.org_id, query, top_k=3, rerank=rerank, exclude_claim_id=claim.id,
                     embedder=embedder, reranker=reranker) if query.strip() else None
    sources = found.hits if found else []
    if not sources:
        return HistorySummary("No similar prior claims found in this org's history.", [], False)

    blocks = "\n".join(
        f'<source id="{i}">\n{neutralize_tags(clean_text(s.snippet, 600))}\n</source>'
        for i, s in enumerate(sources, start=1)
    )
    prompt = SUMMARY_PROMPT.format(
        notice=UNTRUSTED_NOTICE, current=neutralize_tags(clean_text(query, 600)), sources=blocks
    )
    text = get_llm_client().complete(prompt)
    cleaned, removed, grounded = check_citations(text, len(sources))
    if removed:
        logger.warning("Removed citations to missing sources: %s", removed)
    return HistorySummary(cleaned, sources, grounded, removed)


def get_history_summary(claim: "models.Claim", db: Session) -> str:
    """Plain text summary, kept for callers that only want the string."""
    if not session_is_postgres(db):
        from app.rag.legacy_retriever import get_history_summary as legacy

        return legacy(claim, db)
    return summarize_history(db, claim).summary
