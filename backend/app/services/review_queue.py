"""
The review queue: claims for one organization, oldest first, each with its latest
suggestion. Kept out of the router like claim_stats.py.

One query, so the page does not cost one extra query per claim.
"""
from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from app import models
from app.models import ClaimStatus


def get_review_queue(
    db: Session,
    org_id: str,
    status: ClaimStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[tuple[models.Claim, models.Suggestion | None, bool]]:
    """Returns (claim, latest suggestion or None, whether that suggestion has feedback)."""
    # Rank each claim's suggestions newest first, and rank only this org's, so the
    # window never reads another tenant's rows. id breaks a tie on created_at.
    ranked = (
        select(
            models.Suggestion,
            func.row_number()
            .over(
                partition_by=models.Suggestion.claim_id,
                order_by=(models.Suggestion.created_at.desc(), models.Suggestion.id.desc()),
            )
            .label("rn"),
        )
        .join(models.Claim, models.Suggestion.claim_id == models.Claim.id)
        .where(models.Claim.org_id == org_id)
        .subquery()
    )
    latest = aliased(models.Suggestion, ranked)

    stmt = (
        select(models.Claim, latest, models.Feedback.id)
        .outerjoin(latest, and_(latest.claim_id == models.Claim.id, ranked.c.rn == 1))
        .outerjoin(models.Feedback, models.Feedback.suggestion_id == latest.id)
        .where(models.Claim.org_id == org_id)
    )
    if status is not None:
        stmt = stmt.where(models.Claim.status == status)
    stmt = stmt.order_by(models.Claim.created_at.asc(), models.Claim.id.asc()).offset(offset).limit(limit)

    return [(claim, suggestion, feedback_id is not None) for claim, suggestion, feedback_id in db.execute(stmt).all()]
