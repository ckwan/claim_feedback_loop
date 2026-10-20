"""Vector and keyword search over claim history notes.

Adds the pgvector extension and a claim_chunks table with two indexes:

  * HNSW on the embedding, for nearest neighbour search by meaning
  * GIN on a generated tsvector, for keyword search

The SQL is written out on purpose, so it is the place to read how each piece works.

Creating the extension needs a superuser (pgvector is not a "trusted" extension).
The Postgres image used in docker-compose runs as one.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "claim_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "tsv",
            sa.dialects.postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
        ),
        sa.UniqueConstraint("claim_id", "chunk_index", name="uq_claim_chunks_claim_index"),
    )
    op.create_index("ix_claim_chunks_org_id", "claim_chunks", ["org_id"])

    # m: links kept per node. ef_construction: candidates considered while building.
    # Higher values give better recall and a slower, larger index.
    op.execute(
        "CREATE INDEX ix_claim_chunks_embedding_hnsw ON claim_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute("CREATE INDEX ix_claim_chunks_tsv ON claim_chunks USING gin (tsv)")


def downgrade() -> None:
    op.drop_table("claim_chunks")
    # The extension is left installed. Other tables may use it.
