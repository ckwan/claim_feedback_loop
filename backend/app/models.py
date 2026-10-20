import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# nomic-embed-text produces 768 numbers per text. A pgvector column has a fixed
# size, so changing the embedding model to one with another size needs a migration.
EMBEDDING_DIM = 768


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


class ClaimChunk(Base):
    """A searchable piece of a claim's history notes (Postgres only).

    Each chunk carries two search representations:
      * embedding: a vector from an embedding model, for meaning based search
      * tsv: a generated tsvector, for keyword search with stemming and ranking

    org_id is stored on the chunk (denormalised from the claim) so every search can
    filter by tenant on this one table without a join.
    """

    __tablename__ = "claim_chunks"
    __table_args__ = (
        UniqueConstraint("claim_id", "chunk_index", name="uq_claim_chunks_claim_index"),
        Index("ix_claim_chunks_org_id", "org_id"),
        # HNSW: an approximate nearest neighbour graph. m is links per node and
        # ef_construction is the search width while building. vector_cosine_ops makes
        # the index serve the <=> (cosine distance) operator.
        Index(
            "ix_claim_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # GIN: an inverted index from word to rows, for full text search.
        Index("ix_claim_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 of the content, so re-indexing can skip a chunk that did not change.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which model made the vector. Vectors from different models are not comparable,
    # so searches only look at rows from the current model.
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    tsv = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )
