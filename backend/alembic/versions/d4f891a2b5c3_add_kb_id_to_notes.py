"""add kb_id to notes

Revision ID: d4f891a2b5c3
Revises: c7e92f1b3d04
Create Date: 2026-05-18 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4f891a2b5c3"
down_revision = "043653ceaf21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notes",
        sa.Column(
            "kb_id",
            sa.String(),
            nullable=False,
            server_default="default",
        ),
    )
    op.create_index("ix_notes_kb_id", "notes", ["kb_id"])


def downgrade() -> None:
    op.drop_index("ix_notes_kb_id", table_name="notes")
    op.drop_column("notes", "kb_id")
