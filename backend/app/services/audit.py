"""The claim history: what happened to a claim, who did it, and what changed.

Rows are added to the caller's session and committed with the caller's change, so a
change and its history entry are saved together or not at all.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.models import AuditEventType


def record_event(
    db: Session,
    claim: models.Claim,
    event_type: AuditEventType,
    *,
    field: str | None = None,
    old: object = None,
    new: object = None,
    detail: str | None = None,
    adjuster_id: str | None = None,
) -> None:
    db.add(
        models.AuditEvent(
            org_id=claim.org_id,
            claim_id=claim.id,
            adjuster_id=adjuster_id,
            event_type=event_type.value,
            field=field,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
            detail=detail,
        )
    )


def get_claim_history(db: Session, org_id: str, claim_id: str) -> list[dict]:
    """Newest first. Filtered on org_id as well as claim_id."""
    rows = db.execute(
        select(models.AuditEvent, models.Adjuster.name)
        .outerjoin(models.Adjuster, models.Adjuster.id == models.AuditEvent.adjuster_id)
        .where(models.AuditEvent.org_id == org_id, models.AuditEvent.claim_id == claim_id)
        .order_by(models.AuditEvent.id.desc())
    ).all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "field": e.field,
            "old_value": e.old_value,
            "new_value": e.new_value,
            "detail": e.detail,
            "adjuster_id": e.adjuster_id,
            "adjuster_name": name,
            "created_at": e.created_at,
        }
        for e, name in rows
    ]
