from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_org_id

router = APIRouter(tags=["feedback"])


@router.post(
    "/suggestions/{suggestion_id}/feedback", response_model=schemas.FeedbackOut
)
def record_feedback(
    suggestion_id: str,
    payload: schemas.FeedbackCreate,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    suggestion = db.get(models.Suggestion, suggestion_id)
    if suggestion is None or suggestion.claim.org_id != org_id:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.feedback is not None:
        raise HTTPException(
            status_code=409, detail="Feedback already recorded for this suggestion"
        )

    if payload.action_taken == models.FeedbackAction.OVERRIDDEN and not payload.override_reason:
        raise HTTPException(
            status_code=422,
            detail="override_reason is required when action_taken is 'overridden'",
        )

    feedback = models.Feedback(
        suggestion_id=suggestion_id,
        adjuster_id=payload.adjuster_id,
        action_taken=payload.action_taken,
        final_action=payload.final_action,
        override_reason=payload.override_reason,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


@router.get("/feedback/override-rate")
def override_rate(
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    """
    Quick signal that the feedback loop is 'working': the override rate
    should trend down over time as suggestions get better. Day 2/3 extend
    this to bucket by model_version so you can compare across iterations.
    """
    rows = (
        db.query(models.Feedback)
        .join(models.Suggestion)
        .join(models.Claim)
        .filter(models.Claim.org_id == org_id)
        .all()
    )
    if not rows:
        return {"total": 0, "overridden": 0, "override_rate": None}

    overridden = sum(1 for r in rows if r.action_taken == models.FeedbackAction.OVERRIDDEN)
    return {
        "total": len(rows),
        "overridden": overridden,
        "override_rate": round(overridden / len(rows), 3),
    }
