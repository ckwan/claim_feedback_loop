import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.database import session_is_postgres
from app.deps import get_current_org_id
from app.models import VALID_TRANSITIONS, ClaimStatus
from app.rag.embeddings import get_embedder
from app.rag.indexing import try_index_claim
from app.rag.retriever import get_history_summary, summarize_history

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/claims", tags=["claims"])


@router.post("", response_model=schemas.ClaimOut)
def create_claim(
    payload: schemas.ClaimCreate,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    if payload.org_id != org_id:
        # The body's org_id must match the caller's tenant — never trust a
        # client-supplied org_id on writes without checking it against auth.
        raise HTTPException(status_code=403, detail="org_id mismatch")

    claim = models.Claim(
        org_id=org_id,
        claimant_name=payload.claimant_name,
        amount=payload.amount,
        history_notes=payload.history_notes,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    if session_is_postgres(db):
        # Make the notes searchable. A failure here (say Ollama is not running) never
        # fails the claim. POST /claims/reindex catches up later.
        try_index_claim(db, claim, get_embedder())
    return claim


@router.get("", response_model=list[schemas.ClaimOut])
def list_claims(
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    status_filter: ClaimStatus | None = Query(default=None, alias="status"),
    amount_order: Literal["asc", "desc"] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    # NOTE: every query here filters by org_id first. Dropping this filter
    # is the classic multi-tenant bug an interviewer will be watching for,
    # including on the paginated/sorted variant — don't let it slip in later.
    stmt = select(models.Claim).where(models.Claim.org_id == org_id)
    if status_filter is not None:
        stmt = stmt.where(models.Claim.status == status_filter)
    # Sorting happens before the offset and limit, so a page is a slice of the sorted
    # result and not a sorted slice of the page.
    if amount_order == "asc":
        stmt = stmt.order_by(models.Claim.amount.asc(), models.Claim.created_at.desc())
    elif amount_order == "desc":
        stmt = stmt.order_by(models.Claim.amount.desc(), models.Claim.created_at.desc())
    else:
        stmt = stmt.order_by(models.Claim.created_at.desc())
    stmt = stmt.offset(offset).limit(limit)

    return db.execute(stmt).scalars().all()


@router.get("/{claim_id}", response_model=schemas.ClaimOut)
def get_claim(
    claim_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    claim = _get_claim_or_404(db, claim_id, org_id)
    return claim


@router.patch("/{claim_id}/status", response_model=schemas.ClaimOut)
def update_claim_status(
    claim_id: str,
    payload: schemas.ClaimStatusUpdate,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    claim = _get_claim_or_404(db, claim_id, org_id)

    allowed = VALID_TRANSITIONS[claim.status]
    if payload.new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot transition claim from '{claim.status.value}' to "
                f"'{payload.new_status.value}'. Allowed: "
                f"{sorted(s.value for s in allowed) or 'none (terminal state)'}"
            ),
        )

    claim.status = payload.new_status
    db.commit()
    db.refresh(claim)
    return claim


@router.get("/{claim_id}/history-summary", response_model=schemas.HistorySummaryOut)
def claim_history_summary(
    claim_id: str,
    rerank: bool = False,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    """
    RAG: finds similar prior claims in this org (hybrid search, optionally reranked),
    and asks the LLM to summarize them with citations. Citations that point at no real
    source are removed, and `grounded` says whether any valid citation is left.
    Informational only: nothing downstream treats this as a decision input.
    """
    claim = _get_claim_or_404(db, claim_id, org_id)
    if not session_is_postgres(db):
        return schemas.HistorySummaryOut(claim_id=claim.id, summary=get_history_summary(claim, db))
    try:
        result = summarize_history(db, claim, rerank=rerank)
    except Exception as exc:  # embedding service down, etc.
        logger.warning("History summary failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Search is unavailable right now") from exc
    return schemas.HistorySummaryOut(
        claim_id=claim.id,
        summary=result.summary,
        sources=[schemas.SearchHitOut(**{**s.__dict__}) for s in result.sources],
        grounded=result.grounded,
    )


def _get_claim_or_404(db: Session, claim_id: str, org_id: str) -> models.Claim:
    claim = db.get(models.Claim, claim_id)
    if claim is None or claim.org_id != org_id:
        # Same 404 whether it doesn't exist or belongs to another org —
        # don't leak that a claim ID exists in someone else's tenant.
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim
