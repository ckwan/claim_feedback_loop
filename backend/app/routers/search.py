import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db, session_is_postgres
from app.deps import get_current_org_id
from app.rag.embeddings import get_embedder
from app.rag.indexing import reindex_org
from app.rag.retriever import SearchUnavailable, retrieve

logger = logging.getLogger(__name__)

# Included before the claims router so "/claims/search" is not read as a claim id.
router = APIRouter(prefix="/claims", tags=["search"])


@router.get("/search", response_model=schemas.SearchOut)
def search_claims(
    q: str = Query(min_length=2, max_length=500, description="What to look for"),
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid",
    top_k: int = Query(default=5, ge=1, le=20),
    rerank: bool = Query(default=False, description="Let the LLM reorder the top candidates"),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    """Search this organization's claim history notes. Results never cross tenants."""
    try:
        result = retrieve(db, org_id, q, mode=mode, top_k=top_k, rerank=rerank)
    except SearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # the embedding service is down or misconfigured
        logger.warning("Search failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Search is unavailable right now") from exc
    return schemas.SearchOut(
        query=result.query,
        mode=result.mode,
        reranked=result.reranked,
        embedding_model=result.embedding_model,
        results=[schemas.SearchHitOut(**h.__dict__) for h in result.hits],
        timings_ms=result.timings_ms,
    )


@router.post("/reindex", response_model=schemas.ReindexOut)
def reindex(db: Session = Depends(get_db), org_id: str = Depends(get_current_org_id)):
    """Index any of this organization's claims that are missing or changed. Safe to repeat."""
    if not session_is_postgres(db):
        raise HTTPException(status_code=503, detail="Search needs Postgres with pgvector.")
    return reindex_org(db, org_id, get_embedder())
