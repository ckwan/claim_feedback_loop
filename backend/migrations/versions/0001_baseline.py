"""Baseline: the five tables the app had before vector search.

Databases created by the old `Base.metadata.create_all` already have these tables,
so this migration does nothing for them and Alembic simply records that they are at
revision 0001. A new database gets the tables here.

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("organizations"):
        return

    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "adjusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_adjusters_org_id", "adjusters", ["org_id"])
    op.create_table(
        "claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("claimant_name", sa.String(255), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("OPEN", "UNDER_REVIEW", "APPROVED", "DENIED", name="claimstatus"),
            nullable=False,
        ),
        sa.Column("history_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_claims_org_id", "claims", ["org_id"])
    op.create_index("ix_claims_org_id_status", "claims", ["org_id", "status"])
    op.create_table(
        "suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("suggested_action", sa.String(255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_suggestions_claim_id", "suggestions", ["claim_id"])
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "suggestion_id", sa.String(36), sa.ForeignKey("suggestions.id"),
            nullable=False, unique=True,
        ),
        sa.Column("adjuster_id", sa.String(36), sa.ForeignKey("adjusters.id"), nullable=False),
        sa.Column(
            "action_taken",
            sa.Enum("ACCEPTED", "OVERRIDDEN", name="feedbackaction"),
            nullable=False,
        ),
        sa.Column("final_action", sa.String(255), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("suggestions")
    op.drop_table("claims")
    op.drop_table("adjusters")
    op.drop_table("organizations")
    op.execute("DROP TYPE IF EXISTS feedbackaction")
    op.execute("DROP TYPE IF EXISTS claimstatus")
