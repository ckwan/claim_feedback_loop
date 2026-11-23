"""Writing claim notes into the search table.

Indexing is idempotent. Each chunk stores a hash of its text and the name of the model
that embedded it, so running it again only does work for notes that changed or for a
new embedding model.
"""
from __future__ import annotations

import hashlib
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models
from app.rag.chunking import chunk_text
from app.rag.embeddings import Embedder

logger = logging.getLogger(__name__)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def index_claim(db: Session, claim: models.Claim, embedder: Embedder) -> int:
    """Index one claim. Returns how many chunks were written (0 if nothing changed)."""
    chunks = chunk_text(claim.history_notes)
    wanted = {i: _hash(c) for i, c in enumerate(chunks)}

    rows = db.execute(
        select(models.ClaimChunk.chunk_index, models.ClaimChunk.content_hash, models.ClaimChunk.embedding_model)
        .where(models.ClaimChunk.claim_id == claim.id, models.ClaimChunk.org_id == claim.org_id)
    ).all()
    have = {r.chunk_index: r.content_hash for r in rows}
    same_model = all(r.embedding_model == embedder.name for r in rows)
    if have == wanted and same_model:
        return 0

    vectors = embedder.embed_documents(chunks)  # may raise EmbeddingError. Nothing written yet.
    db.execute(delete(models.ClaimChunk).where(models.ClaimChunk.claim_id == claim.id))
    for i, (content, vector) in enumerate(zip(chunks, vectors)):
        db.add(
            models.ClaimChunk(
                claim_id=claim.id,
                org_id=claim.org_id,
                chunk_index=i,
                content=content,
                content_hash=wanted[i],
                embedding_model=embedder.name,
                embedding=vector,
            )
        )
    db.commit()
    return len(chunks)


def try_index_claim(db: Session, claim: models.Claim, embedder: Embedder) -> bool:
    """Index without ever failing the caller. A claim must save even if Ollama is down."""
    try:
        index_claim(db, claim, embedder)
        return True
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Could not index claim %s: %s. Run the reindex to retry.", claim.id, type(exc).__name__)
        return False


def reindex_org(db: Session, org_id: str, embedder: Embedder) -> dict[str, int]:
    """Index every claim of one organization. Safe to run repeatedly."""
    claims = db.execute(select(models.Claim).where(models.Claim.org_id == org_id)).scalars().all()
    result = {"claims": len(claims), "indexed": 0, "unchanged": 0, "failed": 0}
    for claim in claims:
        try:
            written = index_claim(db, claim, embedder)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("Reindex failed for claim %s: %s", claim.id, type(exc).__name__)
            result["failed"] += 1
            continue
        result["indexed" if written else "unchanged"] += 1
    return result
