from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_org_id
from app.routers.claims import _get_claim_or_404
from app.services.suggestion_service import MODEL_VERSION, generate_suggestion

router = APIRouter(tags=["suggestions"])


@router.post("/claims/{claim_id}/suggest", response_model=schemas.SuggestionOut)
def create_suggestion(
    claim_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    claim = _get_claim_or_404(db, claim_id, org_id)

    # All suggestion-generation logic (stub today, LLM + few-shot context on
    # Day 2) lives in the service layer, not here. This handler only does
    # HTTP concerns: look up the claim, call the service, persist the result.
    action, rationale, confidence = generate_suggestion(claim, db)

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
