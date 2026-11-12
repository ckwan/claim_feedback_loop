"""Idempotent intake: an external reference per claim.

Adds claims.external_ref and a partial unique index on (org_id, external_ref) for the
rows that have one. Two orgs may use the same reference. Claims without a reference
are not affected.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("external_ref", sa.String(128), nullable=True))
    op.create_index(
        "uq_claims_org_external_ref",
        "claims",
        ["org_id", "external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_claims_org_external_ref", table_name="claims")
    op.drop_column("claims", "external_ref")
