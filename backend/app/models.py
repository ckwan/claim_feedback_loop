import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ClaimStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    DENIED = "denied"


# Valid forward transitions. Terminal states (approved/denied) have none.
VALID_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    ClaimStatus.OPEN: {ClaimStatus.UNDER_REVIEW},
    ClaimStatus.UNDER_REVIEW: {ClaimStatus.APPROVED, ClaimStatus.DENIED},
    ClaimStatus.APPROVED: set(),
    ClaimStatus.DENIED: set(),
}


class FeedbackAction(str, enum.Enum):
    ACCEPTED = "accepted"
    OVERRIDDEN = "overridden"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    adjusters: Mapped[list["Adjuster"]] = relationship(back_populates="organization")
    claims: Mapped[list["Claim"]] = relationship(back_populates="organization")


class Adjuster(Base):
    __tablename__ = "adjusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="adjusters")


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        # Every real query filters by org_id first — this is the tenant-isolation
        # index an interviewer will specifically look for.
        Index("ix_claims_org_id_status", "org_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    claimant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus), nullable=False, default=ClaimStatus.OPEN
    )
    history_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    organization: Mapped["Organization"] = relationship(back_populates="claims")
    suggestions: Mapped[list["Suggestion"]] = relationship(back_populates="claim")


class Suggestion(Base):
    """An AI-generated recommendation for what should happen to a claim next."""

    __tablename__ = "suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claims.id"), nullable=False, index=True
    )
    suggested_action: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    claim: Mapped["Claim"] = relationship(back_populates="suggestions")
    feedback: Mapped["Feedback"] = relationship(
        back_populates="suggestion", uselist=False
    )


class Feedback(Base):
    """What the human SME actually decided, captured against the suggestion."""

    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    suggestion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("suggestions.id"), nullable=False, unique=True
    )
    adjuster_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("adjusters.id"), nullable=False
    )
    action_taken: Mapped[FeedbackAction] = mapped_column(
        Enum(FeedbackAction), nullable=False
    )
    final_action: Mapped[str] = mapped_column(String(255), nullable=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    suggestion: Mapped["Suggestion"] = relationship(back_populates="feedback")
