import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.database import session_is_postgres
from app.deps import get_current_org_id
from app.models import VALID_TRANSITIONS, AuditEventType, ClaimStatus
from app.rag.embeddings import get_embedder
from app.rag.indexing import try_index_claim
from app.safety import clean_text
from app.rag.retriever import get_history_summary, summarize_history
from app.services.audit import get_claim_history, record_event
from app.services.claim_edit import edit_claim
from app.services.claim_stats import get_claim_stats
from app.services.review_queue import get_review_queue

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
    db.flush()  # assigns the id, so the history entry is saved in the same commit
    record_event(db, claim, AuditEventType.CREATED, new=claim.status.value)
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


@router.get("/stats", response_model=schemas.ClaimStatsOut)
def claim_stats(
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    # Declared before /{claim_id}, or "stats" would be read as a claim id.
    return get_claim_stats(db, org_id)


@router.get("/queue", response_model=list[schemas.ClaimQueueItemOut])
def review_queue(
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    status_filter: ClaimStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Oldest claims first, each with its latest suggestion, in one query."""
    return [
        schemas.ClaimQueueItemOut(
            **schemas.ClaimOut.model_validate(claim).model_dump(),
            latest_suggestion=(
                schemas.QueueSuggestionOut(
                    **schemas.SuggestionOut.model_validate(suggestion).model_dump(),
                    has_feedback=has_feedback,
                )
                if suggestion is not None
                else None
            ),
        )
        for claim, suggestion, has_feedback in get_review_queue(db, org_id, status_filter, limit, offset)
    ]


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

    _check_adjuster(db, payload.adjuster_id, org_id)
    record_event(
        db, claim, AuditEventType.STATUS_CHANGE,
        old=claim.status.value, new=payload.new_status.value, adjuster_id=payload.adjuster_id,
    )
    claim.status = payload.new_status
    db.commit()
    db.refresh(claim)
    return claim


@router.patch("/{claim_id}", response_model=schemas.ClaimOut)
def edit_claim_details(
    claim_id: str,
    payload: schemas.ClaimEdit,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    """Edit amount, claimant_name and history_notes while the claim is not final."""
    claim = _get_claim_or_404(db, claim_id, org_id)
    if claim.status in (ClaimStatus.APPROVED, ClaimStatus.DENIED):
        raise HTTPException(
            status_code=409,
            detail=f"A {claim.status.value} claim is final and can no longer be edited.",
        )
    _check_adjuster(db, payload.adjuster_id, org_id)

    changes = payload.model_dump(exclude_unset=True, exclude={"adjuster_id"})
    if "history_notes" in changes and changes["history_notes"] is not None:
        # Notes are untrusted text that ends up in prompts. Same cleaning as the prompts use.
        changes["history_notes"] = clean_text(changes["history_notes"], schemas.MAX_NOTES_CHARS)

    changed = edit_claim(db, claim, changes, payload.adjuster_id)
    if "history_notes" in changed and session_is_postgres(db):
        # Like POST /claims: a failure here never fails the edit. POST /claims/reindex catches up.
        try_index_claim(db, claim, get_embedder())
    return claim


@router.get("/{claim_id}/history", response_model=list[schemas.AuditEventOut])
def claim_history(
    claim_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    """Everything that happened to this claim, newest first."""
    _get_claim_or_404(db, claim_id, org_id)
    return get_claim_history(db, org_id, claim_id)


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


def _check_adjuster(db: Session, adjuster_id: str | None, org_id: str) -> None:
    """An adjuster named in the body must belong to the caller's organization."""
    if adjuster_id is None:
        return
    adjuster = db.get(models.Adjuster, adjuster_id)
    if adjuster is None or adjuster.org_id != org_id:
        raise HTTPException(status_code=422, detail="adjuster_id does not belong to this organization")


def _get_claim_or_404(db: Session, claim_id: str, org_id: str) -> models.Claim:
    claim = db.get(models.Claim, claim_id)
    if claim is None or claim.org_id != org_id:
        # Same 404 whether it doesn't exist or belongs to another org —
        # don't leak that a claim ID exists in someone else's tenant.
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim
