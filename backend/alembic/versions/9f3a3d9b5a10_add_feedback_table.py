"""add feedback table

Revision ID: 9f3a3d9b5a10
Revises: 201356773e75
Create Date: 2026-04-01 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "9f3a3d9b5a10"
down_revision = "201356773e75"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("feedback")
