"""add failed field to notes

Revision ID: b1c2d3e4f5a6
Revises: 9f3a3d9b5a10
Create Date: 2026-04-16 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = "9f3a3d9b5a10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notes",
        sa.Column("failed", sa.Boolean(), nullable=True, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("notes", "failed")
