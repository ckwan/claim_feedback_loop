"""
Loads claim history notes into the vector store.

Real RAG ingestion chunks long documents before embedding. Claim
`history_notes` here are short (a sentence or two), so chunking is a no-op
in practice — each claim's notes are indexed as a single chunk. The
function signature still takes a `chunk_size` so the seam for real chunking
logic is visible and easy to extend later without changing callers.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.rag.vectorstore import InMemoryVectorStore


def ingest_org_claim_history(
    db: Session, org_id: str, store: InMemoryVectorStore, chunk_size: int = 500
) -> int:
    """
    Indexes every claim's history_notes for one org into `store`. Returns
    the number of documents indexed. Tenant-scoped at the query level, same
    as every other claim lookup in this project.
    """
    stmt = select(models.Claim).where(
        models.Claim.org_id == org_id,
        models.Claim.history_notes.is_not(None),
    )
    claims = db.execute(stmt).scalars().all()

    count = 0
    for claim in claims:
        for chunk in _chunk(claim.history_notes, chunk_size):
            store.add(doc_id=claim.id, text=chunk, org_id=org_id)
            count += 1
    return count


def _chunk(text: str, chunk_size: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
