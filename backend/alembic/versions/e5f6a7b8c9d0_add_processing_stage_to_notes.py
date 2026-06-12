"""add processing stage to notes

Revision ID: e5f6a7b8c9d0
Revises: d4f891a2b5c3
Create Date: 2026-06-11 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4f891a2b5c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notes", sa.Column("processing_stage", sa.String(), nullable=True))
    op.add_column("notes", sa.Column("processing_model", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("notes", "processing_model")
    op.drop_column("notes", "processing_stage")
