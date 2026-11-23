"""Creating a claim, safely repeatable when the caller supplies an external_ref.

An outside system that retries after a timeout must not end up with two claims. The
rule is per organization: the same (org_id, external_ref) is always the same claim.

Two layers hold it. A lookup first handles an ordinary retry. A partial unique index
handles two retries that arrive at once: both can pass the lookup, but the database
lets only one INSERT through, and the loser re-reads and returns the winner's row.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.models import AuditEventType
from app.services.audit import record_event

logger = logging.getLogger(__name__)

COMPARED_FIELDS = ("claimant_name", "amount", "history_notes")


def _find(db: Session, org_id: str, external_ref: str) -> models.Claim | None:
    return db.execute(
        select(models.Claim).where(
            models.Claim.org_id == org_id, models.Claim.external_ref == external_ref
        )
    ).scalar_one_or_none()


def _note_if_payload_differs(existing: models.Claim, payload: dict) -> None:
    """Warn when a retry sent different data. Field names only: no claim content in logs."""
    differing = [f for f in COMPARED_FIELDS if getattr(existing, f) != payload[f]]
    if differing:
        logger.warning(
            "Retried intake for claim %s (org %s) differs from the stored claim in: %s. "
            "Returning the stored claim unchanged.",
            existing.id, existing.org_id, ", ".join(differing),
        )


def create_or_get_claim(
    db: Session,
    org_id: str,
    *,
    claimant_name: str,
    amount: float,
    history_notes: str | None,
    external_ref: str | None,
) -> tuple[models.Claim, bool]:
    """Returns (claim, created). created is False when an existing claim was returned.

    An existing claim is returned as it is. Nothing is written for it: no update, no
    history row, no re-indexing.
    """
    payload = {"claimant_name": claimant_name, "amount": amount, "history_notes": history_notes}

    if external_ref is not None:
        existing = _find(db, org_id, external_ref)
        if existing is not None:
            _note_if_payload_differs(existing, payload)
            return existing, False

    claim = models.Claim(org_id=org_id, external_ref=external_ref, **payload)
    try:
        db.add(claim)
        db.flush()  # assigns the id and raises here if the unique index is hit
        record_event(db, claim, AuditEventType.CREATED, new=claim.status.value)
        db.commit()
    except IntegrityError:
        db.rollback()  # the claim and its history row go together
        existing = _find(db, org_id, external_ref) if external_ref is not None else None
        if existing is None:
            raise  # not our race: a real integrity error
        _note_if_payload_differs(existing, payload)
        return existing, False

    db.refresh(claim)
    return claim, True
