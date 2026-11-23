"""
Claim statistics for one organization.

Kept out of `app/routers/claims.py` so the router stays a thin HTTP layer, the
same split as suggestion_service.py. Everything is computed with GROUP BY in the
database, so no claim or feedback rows are loaded into Python.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.models import ClaimStatus, FeedbackAction


def _rate(part: int, whole: int) -> float | None:
    # None, not 0, when there is nothing to divide by: "no data" is not "0%".
    # Rounded to 3 places like GET /feedback/override-rate.
    return round(part / whole, 3) if whole else None


def get_claim_stats(db: Session, org_id: str) -> dict:
    # Every query filters by org_id, the tenant boundary. Feedback has no org_id
    # column, so it is reached through Suggestion and Claim like override_rate does.
    status_rows = db.execute(
        select(models.Claim.status, func.count())
        .where(models.Claim.org_id == org_id)
        .group_by(models.Claim.status)
    ).all()
    by_status = {s.value: 0 for s in ClaimStatus}
    for status, n in status_rows:
        by_status[status.value] = n

    action_rows = db.execute(
        select(models.Feedback.action_taken, func.count())
        .join(models.Suggestion, models.Feedback.suggestion_id == models.Suggestion.id)
        .join(models.Claim, models.Suggestion.claim_id == models.Claim.id)
        .where(models.Claim.org_id == org_id)
        .group_by(models.Feedback.action_taken)
    ).all()
    actions = {a: n for a, n in action_rows}
    accepted = actions.get(FeedbackAction.ACCEPTED, 0)
    overridden = actions.get(FeedbackAction.OVERRIDDEN, 0)

    approved = by_status[ClaimStatus.APPROVED.value]
    denied = by_status[ClaimStatus.DENIED.value]

    return {
        "by_status": by_status,
        "total": sum(by_status.values()),
        "decisions": {
            "accepted": accepted,
            "overridden": overridden,
            "override_rate": _rate(overridden, accepted + overridden),
        },
        "approval_rate": _rate(approved, approved + denied),
    }
