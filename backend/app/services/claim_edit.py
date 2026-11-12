"""Editing a claim's details, with a history entry per changed field.

Only the three editable fields are ever applied (the router passes nothing else).
Changing the amount or the notes makes the AI's earlier suggestions stale, because
they were written about the old values.
"""
from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from app import models
from app.models import AuditEventType
from app.services.audit import record_event

EDITABLE = ("claimant_name", "amount", "history_notes")
# Editing these changes what a suggestion was based on.
SUGGESTION_INPUTS = ("amount", "history_notes")


def edit_claim(
    db: Session, claim: models.Claim, changes: dict, adjuster_id: str | None = None
) -> list[str]:
    """Apply the changes that differ from the stored values. Returns the changed fields.

    Nothing is written, not even history, when no value is different.
    """
    changed = [f for f in EDITABLE if f in changes and changes[f] != getattr(claim, f)]
    if not changed:
        return []

    for field in changed:
        record_event(
            db, claim, AuditEventType.FIELD_EDIT,
            field=field, old=getattr(claim, field), new=changes[field], adjuster_id=adjuster_id,
        )
        setattr(claim, field, changes[field])

    if any(f in SUGGESTION_INPUTS for f in changed):
        marked = db.execute(
            update(models.Suggestion)
            .where(models.Suggestion.claim_id == claim.id, models.Suggestion.is_stale.is_(False))
            .values(is_stale=True)
        ).rowcount
        if marked:
            record_event(
                db, claim, AuditEventType.SUGGESTIONS_STALE,
                field="suggestions", new=f"marked stale ({marked})", adjuster_id=adjuster_id,
            )

    db.commit()
    db.refresh(claim)
    return changed
