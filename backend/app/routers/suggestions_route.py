from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_org_id
from app.routers.claims_route import _get_claim_or_404
from app.services.suggestions_service import MODEL_VERSION, generate_suggestion

router = APIRouter(tags=["suggestions"])


def _recent_corrections(db: Session, claim: models.Claim) -> str:
    rows = (
        db.query(
            models.Suggestion.suggested_action,
            models.Feedback.final_action,
            models.Feedback.override_reason,
        )
        .select_from(models.Feedback)
        .join(models.Suggestion, models.Feedback.suggestion_id == models.Suggestion.id)
        .join(models.Claim, models.Suggestion.claim_id == models.Claim.id)
        .filter(
            models.Claim.org_id == claim.org_id,
            models.Claim.status == claim.status,
            models.Feedback.action_taken == models.FeedbackAction.OVERRIDDEN,
        )
        .order_by(models.Feedback.created_at.desc())
        .limit(3)
        .all()
    )
    if not rows:
        return ""

    corrections = ["Recent corrections:"]
    corrections.extend(
        f"- {suggested_action} -> {final_action}; reason: {override_reason or 'Not provided'}"
        for suggested_action, final_action, override_reason in rows
    )
    return "\n".join(corrections)


@router.post("/claims/{claim_id}/suggest", response_model=schemas.SuggestionOut)
def create_suggestion(
    claim_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    claim = _get_claim_or_404(db, claim_id, org_id)

    corrections = _recent_corrections(db, claim)
    action, rationale, confidence = generate_suggestion(claim, corrections)

    suggestion = models.Suggestion(
        claim_id=claim.id,
        suggested_action=action,
        rationale=rationale,
        confidence=confidence,
        model_version=MODEL_VERSION,
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    return suggestion


@router.get("/claims/{claim_id}/suggestions", response_model=list[schemas.SuggestionOut])
def list_suggestions(
    claim_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    claim = _get_claim_or_404(db, claim_id, org_id)
    return claim.suggestions
