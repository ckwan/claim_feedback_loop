"""Claim history and stale suggestions.

Adds the audit_events table (an append only history of what happened to a claim) and
suggestions.is_stale (set when the claim is edited after the suggestion was made).

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default so rows that already exist become "not stale" instead of failing NOT NULL.
    op.add_column(
        "suggestions",
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("adjuster_id", sa.String(36), sa.ForeignKey("adjusters.id"), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("field", sa.String(64), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_events_org_claim", "audit_events", ["org_id", "claim_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_column("suggestions", "is_stale")
