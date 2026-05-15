"""drop feedback table

Revision ID: c7e92f1b3d04
Revises: 043653ceaf21
Create Date: 2026-05-14 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c7e92f1b3d04"
down_revision = "043653ceaf21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("feedback")


def downgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("relevance", sa.Integer(), nullable=False),
        sa.Column("quality", sa.Integer(), nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("node_ids_used", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("relevance BETWEEN 1 AND 5", name="feedback_relevance_ck"),
        sa.CheckConstraint("quality BETWEEN 1 AND 5", name="feedback_quality_ck"),
    )
